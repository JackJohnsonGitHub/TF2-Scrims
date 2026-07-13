---
description: "Task list for Sign in with Steam"
---

# Tasks: Sign in with Steam

**Input**: Design documents from `/specs/002-steam-sign-in/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/auth-routes.md, quickstart.md

**Tests**: Included — the plan specifies pytest with **mocked Steam** (`tests/integration/test_auth.py`,
`tests/unit/test_steam.py`); the verification step is security-critical (SC-007), so it is tested.

**Organization**: Tasks are grouped by user story (US1–US3 from spec.md). Extends the existing 001
Flask app; paths at repo root (`app/`, `tests/`, `deploy/`).

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Add `requests` to `requirements.txt` (for Steam OpenID verification + Web API)
- [X] T002 Extend `app/config.py`: require `APP_SECRET_KEY` (session signing), add `STEAM_API_KEY`, `DB_PATH`, `APP_BASE_URL` (OpenID realm/return), and `PERMANENT_SESSION_LIFETIME` (~30 days) — all env-driven, no hardcoded secrets

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 Create `app/db.py`: a `sqlite3` connection helper and idempotent `init_schema()` creating the `users` table (`steam_id` PK, `persona_name`, `avatar_url`, `created_at`, `last_login_at`) per data-model.md
- [X] T004 Create `app/accounts.py`: `upsert_on_login(steam_id, persona_name, avatar_url)` (insert or refresh persona/avatar/last_login) and `get_by_steam_id(steam_id)` per data-model.md
- [X] T005 Create `app/security.py` with a `current_user()` helper resolving the session `steam_id` to its `users` row (or `None` when anonymous)
- [X] T006 Update `app/__init__.py`: call `init_schema()` on startup, apply `PERMANENT_SESSION_LIFETIME`, and register a context processor exposing `current_user` to all templates

**Checkpoint**: DB + account store + `current_user` available to every screen.

---

## Phase 3: User Story 1 - Sign in with Steam (Priority: P1) 🎯 MVP

**Goal**: A visitor can sign in with Steam and see their persona name + avatar in the header.

**Independent Test**: From signed-out, use the header's "Sign in with Steam", complete Steam login,
and return recognized as your account with persona name + avatar shown.

- [X] T007 [P] [US1] Create `app/steam.py`: `build_login_url(base_url)` → Steam OpenID redirect; `verify_return(params)` → validated `steam_id` via server-side `check_authentication` (returns None on failure); `fetch_summary(steam_id)` → `(persona_name, avatar_url)` via the Steam Web API with a fallback when unavailable (research Decisions 1 & 3)
- [X] T008 [US1] Create `app/routes/auth.py` with `GET /login` (302 to Steam) and `GET /login/return` (verify server-side, `upsert_on_login`, set `session['steam_id']` + `session.permanent=True`, redirect to dashboard); register the auth blueprint in `app/__init__.py` (FR-001, FR-002, FR-003, FR-004, FR-012)
- [X] T009 [P] [US1] Create `app/templates/login_error.html` — friendly failure page (cancelled / Steam unavailable / unverifiable) (FR-011)
- [X] T010 [US1] Update `app/templates/base.html` header: when signed in show persona name + avatar (default-avatar fallback); when anonymous show a "Sign in with Steam" control (FR-005)
- [X] T011 [P] [US1] Add header identity styles (avatar, persona) to `app/static/css/app.css`
- [X] T012 [US1] Integration test `tests/integration/test_auth.py` (US1 part): mocked valid return creates a `users` row + session and lands on the dashboard with the persona name in the header; mocked invalid/failed verification sets **no** session and renders `login_error.html` (FR-002, SC-006, SC-007)
- [X] T013 [P] [US1] Unit test `tests/unit/test_steam.py`: `verify_return` accepts a mocked `is_valid:true` and extracts the SteamID, rejects an invalid one; `fetch_summary` falls back cleanly when the Web API is unavailable

**Checkpoint**: US1 works — a real Steam sign-in shows your identity (MVP).

---

## Phase 4: User Story 2 - Owner-only areas require sign-in (Priority: P2)

**Goal**: Owner-only areas are reachable only when signed in; anonymous visitors are sent to sign-in
and returned to where they were headed. A public landing page exists.

**Independent Test**: While signed out, open an owner-only area directly → redirected to sign-in →
after signing in, land on the originally requested area. The landing page is viewable signed out.

- [X] T014 [US2] Add a `login_required` decorator to `app/security.py` that redirects anonymous requests to `/login?next=<original local path>` (FR-007)
- [X] T015 [P] [US2] Create `app/templates/landing.html` — public page with the "Sign in with Steam" call to action (FR-008)
- [X] T016 [US2] Update `app/routes/dashboard.py`: `GET /` renders `landing.html` when anonymous and the dashboard when signed in (FR-008)
- [X] T017 [US2] Apply `@login_required` to the owner-only routes in `app/routes/servers.py` and `app/routes/console.py` (leave `/healthz` public) (FR-007)
- [X] T018 [US2] Update `app/routes/auth.py`: `/login` captures a local-only `next`, and `/login/return` redirects to it after sign-in — reject external/absolute redirect targets (FR-007, open-redirect guard)
- [X] T019 [US2] Extend `tests/integration/test_auth.py`: anonymous `GET /servers` → 302 `/login?next=/servers` and returns there after mocked login; anonymous `GET /` → 200 landing; `GET /healthz` → 200 while anonymous (SC-002)

**Checkpoint**: US1 + US2 — identity now gates access, with a public landing page.

---

## Phase 5: User Story 3 - Stay signed in, and sign out (Priority: P3)

**Goal**: Signed-in state persists across page loads until sign-out or expiry; the user can sign out.

**Independent Test**: Sign in, reload/navigate several pages staying signed in; sign out and confirm
owner-only areas are locked again.

- [X] T020 [US3] Add `GET/POST /logout` to `app/routes/auth.py` (clear the session, redirect to `/`) and a "Sign out" control in the `app/templates/base.html` header when signed in (FR-006)
- [X] T021 [US3] Confirm session persistence/expiry behavior in `app/routes/auth.py` + `app/config.py`: `session.permanent` is set on login and requests past `PERMANENT_SESSION_LIFETIME` are treated as anonymous (FR-004, FR-010)
- [X] T022 [US3] Extend `tests/integration/test_auth.py`: session persists across ≥10 requests without re-login; logout clears the session and re-locks `/servers`; an expired session is treated as anonymous (SC-004, SC-005)

**Checkpoint**: Full identity lifecycle — sign in, stay in, sign out.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update `deploy/deployment.yaml` to mount `APP_SECRET_KEY` + `STEAM_API_KEY` from a Kubernetes Secret and a PVC for the SQLite `DB_PATH`; add `deploy/secret.example.yaml` documenting the OpenBao-sourced keys (no real values)
- [X] T024 [P] Update the `Dockerfile` so the `DB_PATH` directory exists and is writable by the non-root user (e.g. a `/data` mount point); confirm `requests` installs in the deps layer
- [X] T025 [P] Update `README.md` with auth run/build notes (required env: `APP_SECRET_KEY`, `STEAM_API_KEY`, `APP_BASE_URL`, `DB_PATH`) and the exposure caveat (app must be reachable over HTTPS for real Steam sign-in)
- [X] T026 Run the full `quickstart.md` validation and confirm SC-001…SC-007

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Ph1)** → **Foundational (Ph2)** blocks all stories.
- **US1 (Ph3)** depends on Foundational. **This is the MVP.**
- **US2 (Ph4)** depends on US1 (needs the session + auth routes to guard against and return to).
- **US3 (Ph5)** depends on US1 (needs the session to persist/clear).
- **Polish (Ph6)** after the desired stories; T023/T024 (deploy/image) can be done any time after Setup.

### Within Each Story

- US1: `steam.py` (T007) before the auth routes (T008) that use it; header (T010) independent of routes.
- US2: `login_required` (T014) before applying it (T017); `next` handling (T018) pairs with the guard.
- Tests can be written alongside their targets; they assert final behavior.

### Parallel Opportunities

- Setup: T001, T002 independent.
- Foundational: T003→T004 (accounts needs the schema); T005 independent; T006 after T003.
- US1: T007, T009, T011, T013 are [P]; T008 and T010 sequence with the files they touch.
- US2: T015 is [P]; T014→T017→T018 sequence (shared files); T016 independent.
- Polish: T023, T024, T025 are [P]; T026 last.

---

## Parallel Example: User Story 1

```bash
# After Foundational, US1 parallelizable tasks:
Task: "T007 Create app/steam.py (OpenID verify + Web API summary)"
Task: "T009 Create app/templates/login_error.html"
Task: "T011 Add header identity styles to app/static/css/app.css"
Task: "T013 Unit test tests/unit/test_steam.py"
# T008 (auth routes) then T010 (header) run in sequence around them.
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

Setup → Foundational → US1 → **STOP & VALIDATE**: a real Steam sign-in shows your persona + avatar.
That alone proves the identity foundation. (No guard or logout yet — clear cookies to reset.)

### Incremental Delivery

1. Setup + Foundational → DB + account store + `current_user`.
2. US1 → sign in with Steam, see your identity (**MVP**).
3. US2 → owner-only areas gated + public landing page.
4. US3 → stay signed in + sign out (full lifecycle).
5. Polish → secrets/PVC in deploy, image DB path, README, quickstart validation.

---

## Notes

- Total tasks: 26 (Setup 2, Foundational 4, US1 7, US2 6, US3 3, Polish 4).
- Security-critical: `/login/return` MUST complete server-side `check_authentication` before any
  session (SC-007) — covered by T007/T012/T013.
- Secrets (`APP_SECRET_KEY`, `STEAM_API_KEY`) come from OpenBao; never hardcode or log them.
- Real Steam sign-in needs the app reachable over HTTPS with a stable `APP_BASE_URL` — a deployment
  concern (T023 + ingress, tracked in the plan), not blocking local dev with mocked/real Steam.
