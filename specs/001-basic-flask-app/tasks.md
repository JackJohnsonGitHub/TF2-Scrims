---
description: "Task list for Basic App Shell & Container Build"
---

# Tasks: Basic App Shell & Container Build

**Input**: Design documents from `/specs/001-basic-flask-app/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ui-routes.md, quickstart.md

**Tests**: Included — the plan specifies pytest smoke tests (`tests/integration/test_routes.py`,
`tests/unit/test_models.py`) as design artifacts, and quickstart step 2 runs them. They are lightweight
render/validation checks, not full TDD.

**Organization**: Tasks are grouped by user story (US1–US3 from spec.md) so each story is an
independently testable increment.

## Path Conventions

Single server-rendered Flask app; paths at repo root per plan.md: `app/`, `tests/`, `deploy/`,
`Dockerfile`, `.dockerignore`, `wsgi.py`, `requirements.txt`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and structure

- [X] T001 Create the project directory tree per plan.md (`app/`, `app/routes/`, `app/templates/`, `app/static/css/`, `tests/unit/`, `tests/integration/`, `deploy/`) with `__init__.py` files in `app/` and `app/routes/`
- [X] T002 Create `requirements.txt` at repo root with pinned `Flask`, `gunicorn`, and `pytest`
- [X] T003 [P] Create `app/config.py` with env-driven config (bind host/port, a readiness flag) read from environment with sensible defaults
- [X] T004 [P] Create `pytest.ini` (or `pyproject.toml` `[tool.pytest.ini_options]`) at repo root setting `testpaths = tests`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core app scaffolding every screen depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement the Flask application factory `create_app()` in `app/__init__.py`, registering all blueprints (dashboard, servers, console, health) and the 404 handler
- [X] T006 Create the shared layout `app/templates/base.html` with a persistent nav linking Dashboard and Server list (block for page content)
- [X] T007 [P] Create `app/static/css/app.css` giving the app a coherent, legible look across screens (FR-011)
- [X] T008 [P] Implement the readiness endpoint `GET /healthz` in `app/routes/health.py` returning `200 ok` when the app is initialized (FR-008)
- [X] T009 Register a global 404 handler in `app/__init__.py` rendering `app/templates/404.html` with a link back to the dashboard (FR-007)
- [X] T010 Create `wsgi.py` at repo root exposing `app = create_app()` for Gunicorn

**Checkpoint**: App boots, serves `/healthz` and a 404 page, and nav shell renders.

---

## Phase 3: User Story 1 - See and navigate the app's core screens (Priority: P1) 🎯 MVP

**Goal**: Every primary screen renders with placeholder data and is reachable via navigation.

**Independent Test**: Host the app, open it, and confirm you can reach the dashboard, server list,
create-server, and a server detail (with settings + console visible) from the nav, each with
placeholder content.

- [X] T011 [P] [US1] Create the `Server` display view model (dataclass) with `slots_display`/`status_label` helpers and a hard-coded sample collection in `app/models.py` per data-model.md
- [X] T012 [US1] Implement the dashboard blueprint `GET /` in `app/routes/dashboard.py` and template `app/templates/dashboard.html` (nav + example-server summary) (FR-001, FR-002)
- [X] T013 [US1] Implement `GET /servers` in `app/routes/servers.py` and `app/templates/servers_list.html` showing example server rows (name, map, status, `players/max_slots`, address) with an empty-state when the collection is empty (FR-002, FR-003)
- [X] T014 [US1] Implement `GET /servers/new` in `app/routes/servers.py` and `app/templates/server_new.html` rendering the create form fields (name, starting map, max slots, join password) (FR-002, FR-004)
- [X] T015 [US1] Implement `GET /servers/<id>` in `app/routes/servers.py` and `app/templates/server_detail.html` embedding the settings form (prefilled) and the admin-console component (render only); return 404 for unknown ids (FR-002, FR-007)
- [X] T016 [P] [US1] Integration test `tests/integration/test_routes.py`: each screen route returns `200` with its identifying marker, `/healthz` returns `200`, and an unknown path returns `404` (SC-002)

**Checkpoint**: US1 fully functional — the navigable shell is reviewable end-to-end (MVP).

---

## Phase 4: User Story 2 - Interact with the settings and admin-console components (Priority: P2)

**Goal**: Settings form and admin console accept input and give visible feedback (not persisted/executed).

**Independent Test**: Open the settings form and admin console, enter values/commands, and confirm
controls accept input and the UI responds (validation, echoed command, placeholder response) with no
errors.

- [X] T017 [P] [US2] Add presentation-level validation helpers to `app/models.py` (name non-empty ≤64, map non-empty, `max_slots` int 1–32, optional non-empty password) per data-model.md
- [X] T018 [US2] Implement `POST /servers/new` in `app/routes/servers.py`: validate inputs, re-render `server_new.html` with field feedback, and flash a "placeholder — not wired up yet" message; create nothing (FR-004, FR-006)
- [X] T019 [US2] Implement `POST /servers/<id>/settings` in `app/routes/servers.py`: validate + show feedback, not persisted, placeholder flash (FR-004, FR-006)
- [X] T020 [US2] Implement `POST /servers/<id>/console` in `app/routes/console.py`: echo the submitted command into a scrollable output region in `server_detail.html` with a canned placeholder response line (FR-005)
- [X] T021 [P] [US2] Unit test `tests/unit/test_models.py`: validation rules and `slots_display` helper

**Checkpoint**: US1 + US2 both work independently; the interactive components are review-ready.

---

## Phase 5: User Story 3 - Build and run the app as a container the "iriga way" (Priority: P3)

**Goal**: Reproducible iriga-style image (cached deps layer → slim non-root final), pushable to Harbor
and runnable on `mke`, serving the same shell as local.

**Independent Test**: Build the image, run it, confirm `/healthz` is ready within ~15s and every
primary screen loads from the container as it does locally.

- [X] T022 [P] [US3] Create `.dockerignore` at repo root excluding `.git/`, `specs/`, `docs/`, `deploy/`, `tests/`, `.venv/`, `__pycache__/`, and VCS/build noise, mirroring the iriga lean-context approach
- [X] T023 [US3] Create the multi-stage `Dockerfile`: a dependencies stage that `pip install`s from `requirements.txt` only (cached separately from app code), then a `python:3.12-slim` **non-root** final stage that copies `app/` + `wsgi.py` and runs Gunicorn (`gunicorn -b 0.0.0.0:8000 wsgi:app`) (FR-009, Principle V)
- [X] T024 [P] [US3] Create `deploy/deployment.yaml`: Deployment running the Harbor image non-root (`runAsNonRoot`), with CPU/memory requests+limits and a readiness probe on `GET /healthz` (FR-010, Principles VI/VII)
- [X] T025 [P] [US3] Create `deploy/service.yaml`: `ClusterIP` Service (internal-only this phase) targeting the app port
- [X] T026 [US3] Validate the container path per quickstart.md step 3 — **DONE**: `docker build` succeeded (128MB image); `docker run` came ready in ~0.5s (<15s, SC-004); all screens + `/healthz` return 200 and unknown paths 404 from the container (SC-006 parity with local); container runs non-root (uid 10001 appuser); a code-only rebuild reuses the CACHED `pip install` deps layer (FR-009)

**Checkpoint**: All three stories independently functional; app is deployable to `mke`.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T027 [P] Reconcile the Rust→Flask doc conflict: update `docs/tech-context.md` and the `README.md` "Key decisions" table to reflect the Python/Flask control plane (matches Constitution v1.1.0)
- [X] T028 [P] Add run/build notes for the app (local `flask run`, `pytest`, `docker build`) to `README.md`
- [X] T029 Run the full quickstart.md validation and confirm SC-001…SC-006

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup — **blocks all user stories**.
- **User Stories (Phase 3–5)**: all depend on Foundational. US1 → US2 have a light ordering (US2's
  handlers live in the same route files US1 creates); US3 depends only on the app existing (needs
  `wsgi.py` from Foundational + `requirements.txt` from Setup), so US3 can proceed in parallel with US2.
- **Polish (Phase 6)**: after the desired stories are complete.

### User Story Dependencies

- **US1 (P1)**: after Foundational. No dependency on other stories. **This is the MVP.**
- **US2 (P2)**: after US1 (adds POST handlers to the route files + templates US1 created).
- **US3 (P3)**: after Foundational. Independent of US2 — can be built as soon as the app boots.

### Within Each User Story

- Model/validation helpers before routes that use them.
- Route + template before its integration test assertion (test can be written in parallel).

### Parallel Opportunities

- Setup: T003, T004 in parallel.
- Foundational: T007, T008 in parallel (T005/T009 touch `app/__init__.py`; keep sequential).
- US1: T011 and T016 are [P]; T012–T015 all edit `app/routes/servers.py`/templates — sequence T012→T015.
- US2: T017 and T021 are [P]; T018–T020 sequence (shared route files).
- US3: T022, T024, T025 in parallel; T023 then T026.
- Once Foundational is done, a second developer can take US3 while the first does US1→US2.

---

## Parallel Example: User Story 1

```bash
# After Foundational completes, US1 parallelizable tasks:
Task: "T011 Create the Server view model + sample data in app/models.py"
Task: "T016 Integration test in tests/integration/test_routes.py"
# T012–T015 run sequentially (they all touch app/routes/servers.py + templates)
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & VALIDATE** the navigable shell
in a browser (SC-001, SC-002, SC-005) → demo. This alone satisfies the "get the UI components" goal.

### Incremental Delivery

1. Setup + Foundational → app boots (`/healthz`, 404, nav).
2. US1 → navigable shell with placeholder data (**MVP** — the reviewable UI).
3. US2 → interactive settings/console feedback.
4. US3 → containerized the iriga way + deployable to `mke`.
5. Polish → reconcile docs, run full quickstart validation.

---

## Notes

- Total tasks: 29 (Setup 4, Foundational 6, US1 6, US2 5, US3 5, Polish 3).
- All data is placeholder — no cluster calls, no RCON, no persistence this phase (per spec Assumptions).
- T027 clears the outstanding Rust→Flask doc divergence flagged during `/speckit-plan`.
- Commit after each task or logical group; validate each story at its checkpoint before moving on.
