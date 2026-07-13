# Quickstart & Validation: Sign in with Steam

Runnable steps that prove the feature works. Route and data details live in
[contracts/auth-routes.md](./contracts/auth-routes.md) and [data-model.md](./data-model.md).

## Prerequisites

- Python 3.12, and the app from feature 001.
- A **Steam Web API key** (for persona name/avatar) — from OpenBao in real deploys; for local dev,
  export it directly.
- Outbound internet to `steamcommunity.com` / `api.steampowered.com`.
- A Steam account to sign in with.

## 1. Configure and run locally

```bash
. .venv/bin/activate
uv pip install -r requirements.txt          # now includes `requests`
export APP_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export STEAM_API_KEY="<your steam web api key>"
export APP_BASE_URL="http://localhost:5000"  # OpenID realm / return_to
export DB_PATH="./app.db"
flask --app app run --debug                  # http://127.0.0.1:5000
```

**Expected outcomes**

- Visiting `/` while signed out shows the **landing page** with a "Sign in with Steam" button.
- Clicking it sends you to Steam; after you approve, you return signed in and the header shows your
  Steam **persona name and avatar**, plus a **Sign out** control.
- Visiting an owner-only area (e.g. `/servers`) while signed out **redirects to sign-in**; after
  signing in you land back on `/servers`.
- **Sign out** returns you to the landing page; `/servers` again redirects to sign-in.
- `/healthz` returns `200 ok` without signing in.

## 2. Automated tests (no real Steam calls)

```bash
python -m pytest -q
```

**Expected**: `tests/integration/test_auth.py` covers — `/login` redirects to Steam; a mocked valid
return creates a `users` row + session and lands on the dashboard; a mocked invalid return sets **no**
session and shows the error page; anonymous `/servers` → `/login?next=/servers` and returns there
after login; logout clears the session; an expired session is treated as anonymous. `tests/unit/
test_steam.py` covers OpenID return parsing/verification and the avatar fallback.

## 3. Container / cluster notes

- Rebuild the image (now installs `requests`); the multi-stage build and non-root runtime are
  unchanged from 001.
- The Deployment mounts `APP_SECRET_KEY` and `STEAM_API_KEY` from a **Kubernetes Secret sourced from
  OpenBao** (see `deploy/secret.example.yaml`) and a **PVC** for the SQLite file at `DB_PATH`.
- Set `APP_BASE_URL` to the app's real HTTPS origin so Steam returns to the right place. **The app
  must be reachable by users over HTTPS** — 001's ClusterIP-only Service is not enough; add ingress/
  TLS as a deployment step before real sign-in.

## Success-criteria mapping

| Criterion | Validated by |
|---|---|
| SC-001 (sign-in < 30s) | Step 1 sign-in |
| SC-002 (owner-only unreachable when signed out) | Step 1 + `test_auth` guard redirects |
| SC-003 (persona/avatar on every page) | Step 1 header |
| SC-004 (stays signed in across loads) | Step 1 navigation + session test |
| SC-005 (sign-out re-locks areas) | Step 1 logout + test |
| SC-006 (returning user = one account) | `test_auth` re-login upsert |
| SC-007 (forged return never signs in) | `test_auth` invalid-assertion case |
