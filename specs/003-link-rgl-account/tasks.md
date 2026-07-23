# Tasks: Link RGL Account & Schedule Scrims

**Input**: Design documents from `/specs/003-link-rgl-account/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/rgl-routes.md, contracts/scrim-routes.md

**Tests**: Included — the plan's Testing section mandates pytest coverage with the RGL API mocked (link/refresh/unlink, the scrim state machine, same-format enforcement, team-authority checks).

**Organization**: Tasks are grouped by user story so each story is an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 (link RGL), US2 (propose scrim), US3 (open listings)

## Path Conventions

Single Flask app at repo root (extends 001/002): `app/` for source, `tests/unit/` and `tests/integration/` for tests.

---

## Phase 1: Setup

**Purpose**: Schema and configuration groundwork. No new dependencies (plan: Flask, Jinja2, `requests` already present).

- [X] T001 Extend `SCHEMA` in `app/db.py` with the four new tables per data-model.md: `rgl_links` (PK `steam_id` FK→users, profile_name, state, is_verified, is_banned, is_on_probation, linked_at, last_refreshed_at), `rgl_teams` (PK `rgl_team_id`, name, tag, format, division_name, season_id, updated_at), `rgl_memberships` (PK (`steam_id`,`rgl_team_id`), FKs to users/rgl_teams), `scrims` (id PK, format, scheduled_at, origin, proposer_team_id FK, opponent_team_id FK nullable, status, created_by FK, created_at, updated_at, notes nullable). Keep `CREATE TABLE IF NOT EXISTS` idempotent init.
- [X] T002 [P] Add RGL client settings to `app/config.py`: `RGL_API_BASE` (default `https://api.rgl.gg/v0`) and `RGL_TIMEOUT_SECONDS` (short, e.g. 5), overridable via env like the existing Steam settings.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The RGL client, persistence seam, and scheduling gate that US1 populates and US2/US3 depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Create `app/rgl.py` — RGL public API client: `fetch_profile(steam_id)` GETs `{RGL_API_BASE}/profile/{steamid64}` with `requests` and the configured timeout; parse `name`, status flags (`isVerified`/`isBanned`/`isOnProbation`), and `currentTeams` keyed by format (`sixes`/`highlander`/`prolander`, each `id`/`tag`/`name`/`seasonId`/`divisionName` or null). Return an explicit outcome per research.md Decision 2: `ok(profile, teams)`, `no_profile` (404/empty), or `unavailable` (timeout/5xx/network) — never raise to the caller.
- [X] T004 Create `app/rgl_store.py` — persistence for the link (depends on T001, T003 types): `save_link(steam_id, profile, teams)` upserting `rgl_links` (state `linked`/`no_team`/`no_profile`) + `rgl_teams` + rebuilding the user's `rgl_memberships` (dropping teams they left); `get_link(steam_id)`, `get_user_teams(steam_id)`, `get_team(rgl_team_id)`, `is_member(steam_id, rgl_team_id)`, `unlink(steam_id)` (delete link + memberships, keep shared `rgl_teams`).
- [X] T005 Add `rgl_link_required` decorator to `app/security.py` (depends on T004): wraps `login_required` semantics — if the current user has no linked RGL team (`get_user_teams` empty), flash "link RGL / join a team first" and redirect to `/account` (FR-008).
- [X] T006 [P] Extend `tests/conftest.py` with RGL mock fixtures: helpers that monkeypatch `app.rgl.fetch_profile` to return canned outcomes (profile with teams in one/two formats, profile with no teams, `no_profile`, `unavailable`), plus a helper to sign in a test user and link them to a given team (for US2/US3 setups).

**Checkpoint**: Schema, client, store, and gate exist — user stories can now be built.

---

## Phase 3: User Story 1 - Link my RGL account and see my team(s) (Priority: P1) 🎯 MVP

**Goal**: One-click RGL link auto-detected from the signed-in Steam ID; account page shows profile name, current teams grouped by format, status badges, last-refreshed; refresh and unlink work; friendly no-profile/no-team/unavailable handling.

**Independent Test**: Signed in, click "Link RGL account" — profile name and current team(s) appear with no manual ID/URL entry; refresh updates details; unlink removes them (quickstart.md, contracts/rgl-routes.md).

### Tests for User Story 1

> Write these first; ensure they FAIL before implementing.

- [X] T007 [P] [US1] Unit tests in `tests/unit/test_rgl.py`: `fetch_profile` parses name/status flags/teams per format from a mocked response; 404 → `no_profile`; all-null `currentTeams` → empty teams; timeout/5xx → `unavailable`; no exception escapes.
- [X] T008 [P] [US1] Integration tests in `tests/integration/test_rgl_link.py` (mocked RGL, per contracts/rgl-routes.md): `POST /rgl/link` with teams → 302 to `/account`, `rgl_links.state=linked`, team + membership rows exist, `/account` shows teams by format; no-team profile → `state=no_team`, "no current team" shown; 404 → `state=no_profile`, friendly message, no team rows; timeout on `POST /rgl/refresh` → retry flash, prior data unchanged, page 200; `POST /rgl/unlink` → link + memberships gone, "not linked" shown; anonymous `/rgl/*` and `/account` → 302 to login.

### Implementation for User Story 1

- [X] T009 [US1] Create `app/routes/rgl.py` blueprint (depends on T003, T004): `GET /account` (link status, profile name, teams grouped by format, badges, last-refreshed); `POST /rgl/link` and `POST /rgl/refresh` — fetch via `app/rgl.py` using the **session Steam ID only** (no form-supplied ID, FR-002), persist via `rgl_store`, map outcomes to flashes (`unavailable` leaves prior state intact); `POST /rgl/unlink`. All `@login_required`.
- [X] T010 [P] [US1] Create `app/templates/account.html` extending `base.html`: not-linked state with a single "Link RGL account" button; linked state with profile name, verified/banned/probation badges, teams grouped by format (name, tag, division/season), last-refreshed time, Refresh + Unlink buttons; friendly no-profile / no-team / retry messages (FR-006/FR-007).
- [X] T011 [US1] Register the `rgl` blueprint in `app/__init__.py` and add a signed-in "Account" nav link in `app/templates/base.html` (depends on T009, T010).

**Checkpoint**: US1 fully functional — link/refresh/unlink work end-to-end with mocked RGL; T007/T008 pass.

---

## Phase 4: User Story 2 - Propose a scrim to a specific team (Priority: P2)

**Goal**: A member of an RGL-linked team proposes a scrim to a same-format opponent team (team, opponent, future date/time); the opponent's side accepts (→ confirmed) or declines; the proposer can withdraw; either team can cancel a confirmed scrim. All actions membership-checked server-side.

**Independent Test**: As team A, propose to team B; as a team B member, see the incoming pending proposal and accept it; both teams see a confirmed upcoming match. Separately decline one and see it close without a match (contracts/scrim-routes.md).

### Tests for User Story 2

- [X] T012 [P] [US2] Unit tests in `tests/unit/test_scrims.py` for the state machine and validators: `create_proposal` → `pending`; accept → `confirmed`; decline → `declined`; withdraw → `cancelled`; cancel confirmed → `cancelled` (row kept); rejects cross-format opponent, self-scrim, past `scheduled_at`; accept/decline only from `pending`; terminal states immutable; membership required for every transition (actor not on the acting team → rejected).
- [X] T013 [P] [US2] Integration tests in `tests/integration/test_scrims.py` (per contracts/scrim-routes.md): valid `POST /scrims/propose` → 302, scrim `pending`, outgoing for proposer and incoming for an opponent member on `GET /scrims`; opponent member accept → `confirmed`, upcoming for both; **non-member** accept → 403/blocked; cross-format / self / past-time propose → 400 with message; RGL-unlinked user on any `/scrims/*` → redirected with link-first message; anonymous → login redirect; no transition creates any server row (FR-018).

### Implementation for User Story 2

- [X] T014 [US2] Create `app/scrims.py` — data access + state machine (depends on T001, T004): `create_proposal(actor_steam_id, proposer_team_id, opponent_team_id, scheduled_at_utc, notes)` enforcing membership (FR-016), same-format (FR-012), not-self and future-time (FR-017), inserting `origin='proposal'`, `status='pending'`; `accept`/`decline` (opponent-team member only, from `pending`); `withdraw` (proposer-team member, from `pending` → `cancelled`); `cancel` (member of either team, from `confirmed` → `cancelled`, row retained per FR-015); queries `incoming_pending`, `outgoing_pending`, `upcoming_confirmed` for a user's teams; UTC ISO-8601 storage per research.md Decision 6.
- [X] T015 [US2] Create `app/routes/scrims.py` blueprint (depends on T005, T014): `GET /scrims` (incoming/outgoing pending + upcoming across my teams), `GET /scrims/new` (pick my team, same-format opponent teams, future datetime), `POST /scrims/propose`, `POST /scrims/<id>/accept`, `POST /scrims/<id>/decline`, `POST /scrims/<id>/withdraw`, `POST /scrims/<id>/cancel`. All `@login_required` + `@rgl_link_required`; every action re-derives the acting team from the user's own memberships — never trusts a posted team id.
- [X] T016 [P] [US2] Create `app/templates/scrims.html` (my scrims: incoming pending with accept/decline, outgoing pending with withdraw, upcoming confirmed with cancel, times shown in local time) and `app/templates/scrim_new.html` (propose form: my team select, same-format opponent select, datetime-local input).
- [X] T017 [US2] Register the `scrims` blueprint in `app/__init__.py` and add a signed-in "Scrims" nav link in `app/templates/base.html` (depends on T015, T016).

**Checkpoint**: US1 and US2 both work — directed propose → accept/decline/withdraw/cancel round-trips pass T012/T013.

---

## Phase 5: User Story 3 - Post and claim an open scrim listing (Priority: P3)

**Goal**: A team posts an open listing (team, format, date/time, no opponent); other same-format teams browse listings and claim one — first claim wins atomically and confirms the scrim; the owner can cancel an unclaimed listing.

**Independent Test**: As team A, post an open listing; as team B, find it under open listings and claim it; both teams see a confirmed match and the listing leaves the open list; a second claimant is told it's no longer available (contracts/scrim-routes.md).

### Tests for User Story 3

- [X] T018 [P] [US3] Extend `tests/unit/test_scrims.py` with listing transitions: `create_listing` → `open` with `opponent_team_id` NULL; `claim` (same-format, non-owner team) → `confirmed` + opponent set; claim by cross-format team or the owner's own team → rejected; claim of a non-`open` scrim → rejected; owner `cancel_listing` from `open` → `cancelled`; two sequential claims → first wins, second reports taken.
- [X] T019 [P] [US3] Extend `tests/integration/test_scrims.py` with the listing flow: `POST /scrims/listings/new` → listing visible on `GET /scrims/listings` (and filterable by format) and under "my listings" on `/scrims`; claim by a same-format team → `confirmed` for both, gone from open listings; two claims → exactly one confirmed scrim, second gets "no longer available"; owner `POST /scrims/listings/<id>/cancel` → removed, no match; unlinked/anonymous access → redirected.

### Implementation for User Story 3

- [X] T020 [US3] Extend `app/scrims.py` with listings (depends on T014): `create_listing(actor, team_id, scheduled_at_utc, notes)` → `origin='listing'`, `status='open'`, membership + future-time enforced; `claim(actor, scrim_id, claiming_team_id)` validating membership + same-format + not-own-listing, then the atomic first-claim-wins `UPDATE scrims SET status='confirmed', opponent_team_id=? ... WHERE id=? AND status='open'` — 0 rows updated → "no longer available"; `cancel_listing` (owner-team member, from `open`); queries `open_listings(format=None)` and `my_open_listings(user)`.
- [X] T021 [US3] Extend `app/routes/scrims.py` with listing routes (depends on T020): `GET /scrims/listings` (browse open listings, format filter, claim buttons offering only the user's same-format teams), `POST /scrims/listings/new`, `POST /scrims/listings/<id>/claim`, `POST /scrims/listings/<id>/cancel` — all `@login_required` + `@rgl_link_required`, membership re-checked server-side.
- [X] T022 [P] [US3] Create `app/templates/listings.html` (open listings table with format filter and claim action) and add a "my open listings" section with cancel + a "post a listing" form entry point to `app/templates/scrims.html`.

**Checkpoint**: All three stories independently functional — both scheduling paths produce confirmed same-format scrims.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T023 [P] Update `README.md` (feature list + any new env vars from T002) and note outbound HTTPS to `api.rgl.gg` in `deploy/` manifests if egress is restricted (plan: Target Platform).
- [X] T024 Run the full suite (`pytest`) and fix any cross-feature regressions (001/002 suites must stay green alongside the new tests).
- [X] T025 Walk `specs/003-link-rgl-account/quickstart.md` end-to-end against a running dev instance (mocked or real RGL) and fix anything that doesn't match the documented flow.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately.
- **Foundational (Phase 2)**: needs T001 (schema) for T004; T003 is independent of T001. BLOCKS all stories.
- **US1 (Phase 3)**: needs Phase 2. No dependency on US2/US3.
- **US2 (Phase 4)**: needs Phase 2 (gate + store). Functionally exercised via test fixtures that link users (T006), so it is testable without US1's routes — though in production US1 populates the data.
- **US3 (Phase 5)**: needs US2's T014 (`app/scrims.py` core) and T015 (blueprint file) since it extends both.
- **Polish (Phase 6)**: after all desired stories.

### Story Dependency Notes

- US1 (P1) is the MVP and the only story users can exercise on its own.
- US2 and US3 both attach to the same `scrims` entity; US3 extends US2's modules — implement in priority order (P2 → P3).

### Parallel Opportunities

- Phase 1: T002 ∥ T001.
- Phase 2: T003 ∥ T004-prep, T006 ∥ everything (test fixtures, separate file).
- US1: T007 ∥ T008 (different test files); T010 ∥ T009.
- US2: T012 ∥ T013; T016 ∥ T014/T015.
- US3: T018 ∥ T019; T022 ∥ T020/T021.
- Across stories (multiple developers): after Phase 2, US1 (T007–T011) can proceed in parallel with US2 (T012–T017).

---

## Parallel Example: User Story 1

```bash
# Tests first, in parallel (different files):
Task: "Unit tests for RGL client parsing in tests/unit/test_rgl.py"
Task: "Integration tests for link/refresh/unlink in tests/integration/test_rgl_link.py"

# Then implementation; template in parallel with routes:
Task: "RGL routes blueprint in app/routes/rgl.py"
Task: "Account template in app/templates/account.html"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T001–T002) → Phase 2 (T003–T006).
2. Phase 3: US1 (T007–T011).
3. **STOP and VALIDATE**: run `pytest tests/unit/test_rgl.py tests/integration/test_rgl_link.py`; walk the quickstart link flow.
4. Deploy/demo — users can link RGL and see their teams even before any scheduling exists.

### Incremental Delivery

1. Setup + Foundational → foundation ready.
2. US1 → validate → demo (MVP: RGL identity).
3. US2 → validate → demo (directed propose→accept).
4. US3 → validate → demo (open listings→claim).
5. Polish (T023–T025) → full regression + quickstart walk.

---

## Notes

- Tests within each story are written first and must fail before implementation.
- Every scheduling action re-checks membership server-side (FR-016) — never trust posted team ids.
- No task touches servers, payment, or provisioning (FR-018 / Constitution VIII); T013 asserts this.
- Commit after each task or logical group; stop at any checkpoint to validate the story independently.
