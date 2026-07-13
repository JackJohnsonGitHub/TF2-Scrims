# Quickstart & Validation: Basic App Shell & Container Build

Runnable steps that prove this feature works end-to-end. Details of routes and data live in
[contracts/ui-routes.md](./contracts/ui-routes.md) and [data-model.md](./data-model.md).

## Prerequisites

- Python 3.12
- Docker (with BuildKit) for the container path
- For the cluster path: WireGuard tunnel up, access to `harbor.irulast.com` and the `mke` cluster

## 1. Run locally (validates User Story 1 & 2)

```bash
# from repo root
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug        # dev server on http://127.0.0.1:5000
```

**Expected outcomes**

- `http://127.0.0.1:5000/` shows the **dashboard** with navigation.
- Nav reaches `/servers`, `/servers/new`, a server detail (`/servers/<id>`), and its admin console.
- `/servers` lists example servers (name, map, status, `players/max_slots`, address); with no sample
  data it shows an empty-state.
- On a server detail screen, editing the settings fields shows validation feedback; submitting shows a
  "placeholder / not wired up" message (FR-006).
- Typing a command in the admin console and submitting echoes it into the output area with a
  placeholder response (FR-005).
- Visiting `/servers/does-not-exist` shows the friendly 404 with a link back to the dashboard.
- `GET /healthz` returns `200 ok`.

## 2. Run the automated smoke tests

```bash
pip install -r requirements.txt      # includes pytest
pytest -q
```

**Expected**: `tests/integration/test_routes.py` asserts every primary screen returns `200` with its
identifying marker, `/healthz` returns `200`, and an unknown path returns `404`. `tests/unit/` covers
the `Server` view model helpers (`slots_display`, validation).

## 3. Build the container the "iriga way" (validates User Story 3)

```bash
# single buildkit session; deps layer cached separately from app code
DOCKER_BUILDKIT=1 docker build -t harbor.irulast.com/tf2-hosting/app:dev .

# run it and check readiness + shell parity
docker run --rm -p 8000:8000 harbor.irulast.com/tf2-hosting/app:dev &
curl -fsS http://127.0.0.1:8000/healthz     # -> ok, within ~15s of start (SC-004)
curl -fsS http://127.0.0.1:8000/            # -> dashboard HTML
```

**Expected outcomes**

- The build reuses the cached dependency layer on a code-only change (rebuild after editing a template
  is fast; editing `requirements.txt` re-runs the dependency layer) — validates the layered strategy.
- The final image runs as a **non-root** user and serves via Gunicorn.
- Every primary screen loads from the container exactly as it does locally (SC-006).

## 4. Deploy to the cluster (optional, validates SC-006 on `mke`)

```bash
docker push harbor.irulast.com/tf2-hosting/app:dev
kubectl apply -f deploy/deployment.yaml -f deploy/service.yaml
kubectl rollout status deploy/tf2-hosting-app     # readiness probe -> /healthz
# port-forward and confirm the same screens load
kubectl port-forward svc/tf2-hosting-app 8000:80
```

**Expected**: the Deployment reaches Ready (readiness probe passes on `/healthz`), pod runs non-root
with CPU/memory limits, and the port-forwarded app serves the same shell as local.

## Success-criteria mapping

| Criterion | Validated by |
|---|---|
| SC-001 (≤2 nav steps) | Step 1 navigation |
| SC-002 (all screens render, no errors) | Step 1 + Step 2 tests |
| SC-003 (<1s control feedback) | Step 1 settings/console interaction |
| SC-004 (ready <15s, health signal) | Step 3 `curl /healthz` |
| SC-005 (screens self-explanatory) | Step 1 visual review |
| SC-006 (image parity local↔cluster) | Step 3 + Step 4 |
