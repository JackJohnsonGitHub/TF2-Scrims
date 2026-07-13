# Phase 0 Research: Basic App Shell & Container Build

All Technical Context items were resolvable from the constitution, the spec, and the referenced
iriga project. No open `NEEDS CLARIFICATION` markers remain.

## Decision 1 — Web framework & rendering approach

- **Decision**: Flask with server-rendered Jinja2 templates; no SPA/frontend framework.
- **Rationale**: Owner-directed (Flask) and constitutionally mandated (Principle III / Scope). Five
  simple screens with placeholder data do not justify a JS build toolchain (Principle I —
  smallest thing that works). Jinja + one CSS file gives a coherent, legible UI (FR-011).
- **Alternatives considered**: Flask + React/HTMX SPA (rejected: extra build tooling and complexity
  before any behavior exists); FastAPI (rejected: contradicts the owner-directed Flask decision).

## Decision 2 — Production serving

- **Decision**: Serve via Gunicorn (`wsgi.py` exposing the app factory's `app`); the Flask
  development server is used only for local `flask run`.
- **Rationale**: The dev server is explicitly not for production; Gunicorn is the standard WSGI
  server and lets the container report readiness reliably (SC-004).
- **Alternatives considered**: uWSGI (heavier config), Waitress (fine, but Gunicorn is the more common
  Linux-container default).

## Decision 3 — Container build strategy (the "iriga way", translated to Python)

- **Decision**: Multi-stage Dockerfile that (a) installs pinned dependencies into an isolated layer
  from `requirements.txt` only, then (b) copies application code, then (c) produces a slim, non-root
  final runtime image. A lean `.dockerignore` keeps the build context to source + manifests. Built in
  a single buildkit session and pushed to `harbor.irulast.com`.
- **Rationale**: Mirrors iriga's core idea — cook/cache the expensive dependency layer once,
  separately from fast-changing app code, so rebuilds are cheap and deterministic (Principle V). In
  Rust that layer is `cargo chef cook`; the Python equivalent is a `pip install -r requirements.txt`
  step that only re-runs when `requirements.txt` changes. iriga's `.dockerignore` (excludes `.git/`,
  `specs/`, `docs/`, `deploy/`, VCS/build noise) is copied in spirit.
- **Final base options evaluated**:
  - `python:3.12-slim` + a non-root user — **chosen** for this phase: smallest reliable option that
    keeps `pip`/wheels simple, runs non-root, and is well understood.
  - `gcr.io/distroless/python3-debian12:nonroot` — iriga's final images are distroless; attractive for
    a smaller attack surface, but Python distroless pins the interpreter minor version and complicates
    debugging. **Deferred** as a hardening follow-up once the app stabilizes; noted so we can adopt it
    without reworking the multi-stage structure.
- **Alternatives considered**: single-stage build (rejected: no dependency-layer caching, larger image,
  fails Principle V's "deterministic + minimal"); building wheels in a separate stage and copying them
  (viable optimization, deferred — not needed at this dependency count).

## Decision 4 — Readiness / health signal

- **Decision**: A `GET /healthz` endpoint returning 200 when the app is ready; the k8s Deployment
  uses it as a readiness probe.
- **Rationale**: FR-008 + SC-004 require a readiness signal so the cluster does not route traffic to a
  starting pod (edge case: "container not ready").
- **Alternatives considered**: TCP-only probe (rejected: doesn't confirm the app can render); separate
  liveness endpoint (deferred — readiness is sufficient this phase).

## Decision 5 — No persistence, no auth this phase

- **Decision**: Placeholder data lives in-process (`app/models.py`); no database; no login.
- **Rationale**: Spec Assumptions scope both out of this phase; adding them now violates Principle I.
  Exposure is limited to the internal/WireGuard network, and the Service is `ClusterIP` (not
  externally reachable), which satisfies Principle IV for a no-secrets scaffold.
- **Alternatives considered**: SQLite now (rejected: nothing to persist yet); a login stub (rejected:
  no auth surface exists to guard, and network isolation covers this phase — revisit in the auth
  feature).

## Decision 6 — Deployment manifests

- **Decision**: Plain YAML `Deployment` + `Service` under `deploy/`, with CPU/memory
  requests+limits and `runAsNonRoot`.
- **Rationale**: Principle VI (everything as code) and VII (resource limits / blast radius). Plain YAML
  is the smallest option; no Helm on this machine anyway.
- **Alternatives considered**: Helm chart / Kustomize (rejected: premature for one Deployment).
