# Implementation Plan: Basic App Shell & Container Build

**Branch**: `001-basic-flask-app` | **Date**: 2026-07-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-basic-flask-app/spec.md`

## Summary

Stand up the walking skeleton of the TF2 hosting platform: a server-rendered **Flask** web app
whose five primary screens (dashboard, server list, create-server, server settings, admin console)
render and navigate with placeholder data, plus a **reproducible, iriga-style multi-stage container
image** that runs non-root on the `mke` cluster and reports readiness. No cluster calls, no real TF2
server, no RCON, no persistence yet — this feature establishes the UI surface and the deployment path
every later feature builds on.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: Flask (app + Jinja2 templates for server-rendered UI); Gunicorn (production
WSGI server — the Flask dev server is not used in the container). No frontend framework — plain HTML
templates + a small hand-written CSS file for a coherent look.

**Storage**: N/A this phase (no database; placeholder data is in-process; settings changes need not
survive reload).

**Testing**: pytest (+ Flask test client) for route/render smoke tests.

**Target Platform**: Linux container on the bare-metal `mke` Kubernetes cluster; reached over the
internal/WireGuard network.

**Project Type**: Web application (single deployable, server-rendered).

**Performance Goals**: Container ready to serve within 15 s of start (SC-004); UI control feedback
under 1 s (SC-003).

**Constraints**: Minimal, non-root runtime image built the iriga way (dependency layer cached
separately from app code, single buildkit session, pushed to `harbor.irulast.com`); no secrets in
image or logs; internal-network exposure only (no auth this phase).

**Scale/Scope**: Single trusted owner; ~5 primary screens; placeholder data only.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against Constitution v1.1.0:

| Principle | Status | Notes |
|---|---|---|
| I. PoC-First, No Gold-Plating | ✅ Pass | Smallest thing that yields a reviewable UI + deploy path; no billing/auth/persistence added. |
| II. Servers Are Cattle, Not Pets | ✅ N/A this phase | No servers are provisioned yet; the app pod itself is disposable and fully described by manifests. |
| III. Kubernetes-Native Control | ✅ Deferred, not violated | No cluster mutation occurs this phase; when it arrives (later feature) it MUST use the Kubernetes Python client, not `kubectl`. Recorded, nothing to shell out here. |
| IV. Secure by Default | ✅ Pass | No RCON/secrets introduced; none hardcoded or logged. Auth intentionally deferred — exposure limited to the internal/WireGuard network (see Assumptions in spec). |
| V. Reproducible Images | ✅ Pass (this feature delivers it) | Deterministic multi-stage build from pinned base + pinned deps, pushed to Harbor; no hand-mutation of running containers. |
| VI. Everything as Code | ✅ Pass | Dockerfile, `.dockerignore`, and k8s manifests live in-repo under version control. |
| VII. Right-Size the Blast Radius | ✅ Pass | The app Deployment sets CPU/memory requests+limits; internal-only exposure. |

**Result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/001-basic-flask-app/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (UI route contract)
│   └── ui-routes.md
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
app/
├── __init__.py          # Flask application factory (create_app)
├── config.py            # env-driven config (host/port, readiness flag)
├── models.py            # Server display view model (dataclass) + placeholder sample data
├── routes/
│   ├── __init__.py
│   ├── dashboard.py     # "/" dashboard blueprint
│   ├── servers.py       # "/servers", "/servers/new", "/servers/<id>" blueprints
│   ├── console.py       # "/servers/<id>/console" admin-console blueprint (echo + placeholder)
│   └── health.py        # "/healthz" readiness signal
├── templates/
│   ├── base.html        # shared layout + nav
│   ├── dashboard.html
│   ├── servers_list.html
│   ├── server_new.html
│   ├── server_detail.html   # embeds settings form + admin console
│   └── 404.html
└── static/
    └── css/app.css      # single coherent stylesheet

tests/
├── unit/
│   └── test_models.py
└── integration/
    └── test_routes.py   # Flask test client: every primary screen returns 200 + key markers; 404 works

wsgi.py                  # Gunicorn entrypoint (exposes `app`)
requirements.txt         # pinned dependencies (Flask, gunicorn, pytest)
Dockerfile               # iriga-style multi-stage: deps layer → slim non-root final
.dockerignore            # lean build context (mirrors iriga: no .git, specs, docs, tests)
deploy/
├── deployment.yaml      # app Deployment (non-root, resource limits, readiness probe → /healthz)
└── service.yaml         # ClusterIP Service (internal only this phase)
```

**Structure Decision**: Single-project server-rendered web app (not split frontend/backend — Flask
renders Jinja templates directly, which is the smallest thing that delivers the reviewable UI shell
per Principle I). Routes are organized as Flask blueprints per screen area so later features can
attach real behavior without restructuring. Container/deploy assets (`Dockerfile`, `.dockerignore`,
`deploy/`) live at repo root, matching the iriga layout.

## Complexity Tracking

No constitution violations — section intentionally empty.
