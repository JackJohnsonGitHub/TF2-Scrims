# Implementation Plan: Sign in with Steam

**Branch**: `002-steam-sign-in` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-steam-sign-in/spec.md`

## Summary

Add identity to the existing Flask app (feature 001): a public landing page with a "Sign in with
Steam" action, a Steam OpenID login flow verified server-side, a signed-in session that persists
across page loads, the user's Steam persona name + avatar in the header, sign-out, and a route guard
that restricts owner-only areas (their servers, request-a-server, admin console) to signed-in users.
This introduces the app's **first persistence** (a small SQLite user store) and its **first real
secrets** (session-signing key + Steam Web API key, both from OpenBao). No payment and no server
provisioning.

## Technical Context

**Language/Version**: Python 3.12 (extends the 001 app)

**Primary Dependencies**: Flask + Jinja2 (existing); **`requests`** (new) for the Steam OpenID
`check_authentication` server-to-server verification and the Steam Web API persona/avatar lookup;
Gunicorn (existing) for serving. Sessions use Flask's built-in signed-cookie session (no new dep).

**Storage**: **SQLite** (Python stdlib `sqlite3`) for the user-account store — smallest thing that
persists (Principle I); a thin data-access module, leaving room to move to Postgres later. DB file
path is env-configured (local file in dev; a PVC-backed path in the container).

**Testing**: pytest + Flask test client. Steam OpenID verification and the Steam Web API are
**mocked** in tests (no real network) so sign-in, route-guarding, and session behavior are covered
deterministically.

**Target Platform**: same container on the `mke` cluster. New runtime needs: outbound HTTPS to
`steamcommunity.com` / `api.steampowered.com`, a stable base URL (the OpenID realm / return URL), a
persistent volume for the SQLite file, and the two secrets mounted from OpenBao.

**Project Type**: Web application (extends the single server-rendered Flask app).

**Performance Goals**: sign-in completes in under ~30 s excluding Steam's own screens (SC-001); route
guard adds negligible latency.

**Constraints**: identity verified **server-side** before any session (Principle IV); no passwords
stored (FR-009); session-signing key and Steam Web API key come from **OpenBao**, never hardcoded or
logged; sessions expire (default ~30 days) and expired requests are treated as signed out.

**Scale/Scope**: single trusted operator + a small number of team captains; one user row per Steam
identity.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against Constitution v2.1.0:

| Principle | Status | Notes |
|---|---|---|
| I. Ship the Smallest Paid Loop First | ✅ Pass | Auth is the first link of the paid loop; this delivers exactly that link, nothing extra (no requests/payment/provisioning). |
| II. Servers Are Cattle, Not Pets | ✅ N/A | No servers provisioned in this feature. |
| III. Kubernetes-Native Control | ✅ N/A this phase | No cluster mutation; deferred to provisioning features. |
| IV. Secure by Default | ✅ Pass (delivers the auth half) | Steam identity verified server-side; no passwords; secrets from OpenBao; sessions signed + expiring. App still processes **no** payments. |
| V. Reproducible Images | ✅ Pass | Extends the pinned multi-stage image (adds `requests`); build stays deterministic. |
| VI. Everything as Code | ✅ Pass | New k8s Secret reference + PVC + config live in `deploy/` under version control. |
| VII. Right-Size the Blast Radius | ✅ Pass, with note | No per-tenant compute added. Note: sign-in requires the app to be **reachable by users over HTTPS** (a stable realm URL) — an ingress/exposure step tracked as a deployment dependency, not new code here. |
| VIII. Steam-Authenticated, Approved Access | ✅ Pass (implements the "Steam-authenticated" half) | Establishes the Steam identity that later request/approval + provisioning build on. |

**Result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/002-steam-sign-in/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── auth-routes.md   # Phase 1 output (auth + guard route contract)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root) — additions/changes to the 001 app

```text
app/
├── __init__.py          # CHANGED: init DB on startup; register auth blueprint; inject current_user
├── config.py            # CHANGED: required SECRET_KEY, STEAM_API_KEY, DB_PATH, SESSION lifetime, BASE_URL
├── db.py                # NEW: sqlite3 connection helper + schema init (users table)
├── steam.py             # NEW: Steam OpenID (build login URL + verify return) & Web API persona/avatar
├── accounts.py          # NEW: user-account data access (upsert on sign-in, fetch by steam_id)
├── security.py          # NEW: login_required decorator + current_user() helper
├── routes/
│   ├── auth.py          # NEW: GET /login, GET /login/return, GET/POST /logout
│   ├── dashboard.py     # CHANGED: "/" = landing when anonymous, dashboard when signed in
│   ├── servers.py       # CHANGED: guard owner-only routes with @login_required
│   └── console.py       # CHANGED: guard with @login_required
├── templates/
│   ├── base.html        # CHANGED: header shows persona name + avatar + Sign out, or Sign in
│   ├── landing.html     # NEW: public sign-in page ("Sign in with Steam")
│   └── login_error.html # NEW: friendly failure (cancelled / Steam unavailable / unverifiable)
└── static/css/app.css   # CHANGED: header identity + landing styles

tests/
├── unit/
│   └── test_steam.py    # NEW: OpenID return parsing/verification (mocked), avatar fallback
└── integration/
    └── test_auth.py     # NEW: login flow (mocked Steam), guard redirects + return-to, logout, expiry

deploy/
├── deployment.yaml      # CHANGED: mount SECRET_KEY + STEAM_API_KEY from a Secret; PVC for SQLite; env
├── service.yaml         # unchanged (exposure/ingress handled separately — see research)
└── secret.example.yaml  # NEW: documents the OpenBao-sourced keys (no real values committed)
```

**Structure Decision**: Extend the existing single Flask app rather than add a service. Auth concerns
are split into small modules (`steam.py` protocol, `accounts.py` persistence, `security.py` guard,
`routes/auth.py` endpoints) so later features (server requests, provisioning) reuse `current_user`
and the user store without rework. Session state uses Flask's signed-cookie session (the "Session"
entity is realized as a signed, expiring cookie — no session table needed).

## Complexity Tracking

No constitution violations — section intentionally empty.
