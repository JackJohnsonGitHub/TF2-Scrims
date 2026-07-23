# Tasks: Scrims Dashboard, Team Rosters & Attendance

**Input**: Design documents from `/specs/004-scrims-dashboard/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/dashboard-routes.md, quickstart.md

**Tests**: Included — the plan's Technical Context defines the test coverage explicitly (unit +
integration, RGL mocked), continuing the 001–003 TDD convention. Write each story's tests first
and see them fail before implementing.

**Organization**: Grouped by user story so each story is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 (dashboard), US2 (roster detail), US3 (attendance)

## Phase 1: Setup

**Purpose**: Confirm a green baseline — this feature adds no dependencies or scaffolding.

- [X] T001 Run `python3 -m pytest tests/ -q` and confirm the 001–003 suite is green before any changes (record the passing count for the regression checks below)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema, config, and the RGL roster client/persistence that US2/US3 need and US1's
schema shares. Nothing here changes user-visible behavior.

**⚠️ CRITICAL**: Complete before starting any user story phase.

- [X] T002 [P] Add `rgl_rosters`, `rgl_roster_meta`, and `scrim_attendance` tables to `SCHEMA` in app/db.py exactly per specs/004-scrims-dashboard/data-model.md (new tables only — no ALTERs)
- [X] T003 [P] Add `RGL_ROSTER_TTL_SECONDS` (env-driven, default 3600) to app/config.py alongside the existing RGL settings
- [X] T004 [P] Write failing unit tests in tests/unit/test_rgl_roster.py: `fetch_team_roster` parses the verified `/v0/teams/{id}` shape (current = `leftAt == null`, departed excluded, `isLeader` kept), and maps 404 / non-200 / timeout / malformed JSON to outcomes without raising (mirror tests/unit/test_rgl.py mocking style)
- [X] T005 Implement `fetch_team_roster(team_id)` in app/rgl.py returning an outcome dataclass (`ok` with players / `unavailable` / `no_team`), reusing `RGL_API_BASE` + `RGL_TIMEOUT_SECONDS`; make T004 pass
- [X] T006 Implement roster persistence in app/rgl_store.py: `save_roster` (atomic per-team DELETE+INSERT plus `rgl_roster_meta` stamp), `get_roster`, `roster_fetched_at`, and `ensure_roster(team_id)` (fetch only when stamp missing/older than TTL; on failure keep cached rows — research §2), with unit coverage added to tests/unit/test_rgl_roster.py

**Checkpoint**: Foundation ready — roster machinery tested, schema live, user stories can begin.

---

## Phase 3: User Story 1 - Browse the open scrims dashboard from the header (Priority: P1) 🎯 MVP

**Goal**: `/scrims` becomes the combined dashboard — all-format open future listings (soonest
first, own-team rows flagged, inline claim) + my-scrims summary + top-right create/propose actions
+ empty state; past listings vanish via query-time filtering and cannot be claimed;
`/scrims/listings` redirects.

**Independent Test**: Sign in RGL-linked, click "Scrims": one page shows other teams' open
listings and your pending/upcoming scrims; a past-dated listing appears nowhere and can't be
claimed; top-right actions reach the 003 flows; `/scrims/listings` 302s to `/scrims`.

- [X] T007 [P] [US1] Extend tests/unit/test_scrims.py with failing expiry tests: `open_listings()` and `my_open_listings()` exclude rows with past `scheduled_at`; `claim()` on an expired-but-`open` listing raises "no longer available" and leaves the row unchanged
- [X] T008 [P] [US1] Write failing integration tests in tests/integration/test_dashboard.py per contracts/dashboard-routes.md: combined page shows both sections; soonest-first ordering; own-team listing flagged with no claim control; past listing in neither section; empty-state call-to-action; `GET /scrims/listings` → 302 to `/scrims` preserving `?format=`; anonymous → login redirect and unlinked → RGL-link gate on `/scrims`
- [X] T009 [US1] In app/scrims.py add the `now` filter (`scheduled_at > :now`) to `open_listings()` and `my_open_listings()`, and extend `claim()`'s atomic UPDATE with `AND scheduled_at > :now` (data-model.md "Changed queries")
- [X] T010 [US1] In app/routes/scrims.py: make `index()` render the combined dashboard (all-format `open_listings` + optional `?format=` filter + `my_team_ids` + existing my-scrims context); turn `listings()` into a 302 redirect to `scrims.index` preserving `format`; retarget the error/success redirects that pointed at `scrims.listings`
- [X] T011 [US1] Rework app/templates/scrims.html into the combined dashboard: top-right "New listing" + "Propose scrim" actions, open-listings section (team/tag, format, division, local time, own-team badge, inline claim form for eligible rows), my-scrims summary (incoming/outgoing/upcoming/my listings with existing action buttons), and the no-open-listings empty state
- [X] T012 [US1] Delete app/templates/listings.html and update every reference to the `scrims.listings` endpoint/page (templates, and existing assertions in tests/integration/test_scrims.py that expect a standalone listings page) to the merged-dashboard behavior
- [X] T013 [US1] Checkpoint: run tests/unit/test_scrims.py, tests/integration/test_dashboard.py, then the full suite — all green, no 003 regressions

**Checkpoint**: Dashboard is the scrims home; expiry enforced. Independently shippable MVP.

---

## Phase 4: User Story 2 - See the people on a listing's team (Priority: P2)

**Goal**: Clicking a listing opens `/scrims/<id>` showing listing details plus the posting team's
cached RGL roster (leader badge, stale/unavailable handled gracefully), with claim available from
the detail page.

**Independent Test**: From the dashboard, open another team's listing: details + that team's
player list render (or a friendly notice when RGL is down and the cache is cold); claim works from
the detail page; a non-participant gets 404 on a confirmed scrim's detail.

- [X] T014 [P] [US2] Write failing integration tests in tests/integration/test_scrim_detail.py per contracts/dashboard-routes.md: open-listing detail 200 with mocked roster names + leader badge; TTL respected (no refetch when fresh); RGL failure with warm cache → cached names shown; cold cache → "roster unavailable" notice with details still rendered; visibility (open future listing → any linked user; confirmed/cancelled/expired → participants only, others 404; proposal-origin → participants only); claim from detail confirms; expired listing claim from detail → "no longer available"
- [X] T015 [US2] Add `get_scrim_for_viewer(scrim_id, steam_id)` to app/scrims.py implementing the research §6 visibility rule (returns row or None → 404), with unit coverage in tests/unit/test_scrims.py
- [X] T016 [US2] Add `GET /scrims/<int:scrim_id>` to app/routes/scrims.py: resolve scrim via `get_scrim_for_viewer`, call `ensure_roster` for the posting team, pass roster + fetched-at age + claim eligibility (`my_teams`, same-format, not-own, open-and-future) to the template
- [X] T017 [US2] Create app/templates/scrim_detail.html: listing team/format/division/local time/posting age/notes, roster list with leader badge and departed-safe rendering, stale-age note or "roster unavailable" notice, claim form for eligible viewers, link back to `/scrims`
- [X] T018 [US2] Link each dashboard listing row (and my-listings rows) in app/templates/scrims.html to its detail page, then run tests/integration/test_scrim_detail.py + full suite green

**Checkpoint**: US1 + US2 work independently — dashboard rows open rich detail pages.

---

## Phase 5: User Story 3 - Track attendance on my own team's listing (Priority: P3)

**Goal**: On your own team's listing detail, the roster becomes an attendance tracker —
self-marking for members, creator marks anyone (incl. account-less and departed players), tally vs
6/7/9, team-only visibility, editable through claim/confirm until scrim time, read-only after.

**Independent Test**: As listing creator, mark players attending/not attending — tally updates and
persists; a non-creator teammate can change only their own row; opponents/non-members see roster
but zero attendance markup; after the scheduled time, writes are rejected.

- [X] T019 [P] [US3] Write failing unit tests in tests/unit/test_attendance.py: authz matrix (member-self allowed; member-other 403; creator-any allowed; opponent/non-member 403), status whitelist, upsert + `player_name` snapshot, departed-player flag in merged view, tally vs `FORMAT_SIZES` (sixes 6, prolander 7, highlander 9), rejects proposal-origin / cancelled / past-`scheduled_at` scrims (read-only per FR-017)
- [X] T020 [P] [US3] Add failing integration tests to tests/integration/test_scrim_detail.py: tracker + tally render only for posting-team members (assert attendance markup absent for others); `POST /scrims/<id>/attendance` self-mark 302 + persisted; teammate-other 403 unless creator; creator marks account-less roster player; tracker still editable after the listing is claimed, rejected after time passes
- [X] T021 [US3] Create app/attendance.py: `FORMAT_SIZES`, `set_status(actor, scrim_id, player_steam_id, status)` enforcing the data-model.md invariants (listing-origin, posting-team membership, self-or-creator, not cancelled, future `scheduled_at`), `roster_with_attendance(scrim)` merge (statuses + departed flags), `tally(scrim)`; make T019 pass
- [X] T022 [US3] Add `POST /scrims/<int:scrim_id>/attendance` to app/routes/scrims.py (authority failures 403, validation failures flash, redirect back to the detail page) per contracts/dashboard-routes.md
- [X] T023 [US3] Extend app/templates/scrim_detail.html with the tracker for posting-team viewers: per-player status + mark controls (own row for members, all rows for the creator), attending tally vs format size, departed flag, read-only state after scrim time; run tests/unit/test_attendance.py + tests/integration/test_scrim_detail.py + full suite green

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T024 Full-suite validation: `python3 -m pytest tests/ -q` green; compare against the T001 baseline to confirm zero 003 regressions alongside the new coverage
- [X] T025 Execute the specs/004-scrims-dashboard/quickstart.md manual walkthrough against the running app with `python3 scripts/seed_demo_team.py` data (dashboard, redirect, expiry, roster fallback on fake-id demo teams, real roster on own team, claim, attendance), fixing anything it surfaces

---

## Phase 7: Post-Implementation UI Adjustments (user feedback, 2026-07-23)

**Purpose**: Dashboard layout refinements requested after using the implemented feature — decision
record in research.md §7; spec clarifications + FR-002/FR-004/FR-007 updated to match.

- [X] T026 Restructure app/templates/scrims.html into a two-column grid (`.scrims-cols` in app/static/css/app.css): main column = Open listings + "My matches & listings" (upcoming + own listings); right rail = "Proposals" (incoming/outgoing) as compact rail items; collapses under 900px
- [X] T027 Move the post-a-listing form to its own page: new `GET /scrims/listings/new` (`new_listing_form`) rendering app/templates/listing_new.html; POST unchanged, validation errors redirect back to the form page; dashboard/empty-state links point at the page; contract route table updated
- [X] T028 Remove horizontal scrolling from Open listings: widen the scrims screen to 1200px, compact the table to 4 columns (notes under team, division under format as `.cell-sub` lines, times as `YYYY-MM-DD HH:MM` UTC); keep `overflow-x: auto` as a safety net only; full suite re-run green (156 passed)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: none — start immediately.
- **Foundational (Phase 2)**: after T001. T002/T003/T004 are parallel; T005 needs T004 (tests
  first); T006 needs T002 + T005. **Blocks all stories** (US1 needs the schema baseline; US2/US3
  need roster machinery).
- **US1 (Phase 3)**: after Phase 2. T007/T008 parallel first (failing tests); T009 → T010 → T011 →
  T012 → T013 (scrims.py before routes before template; same files are sequential).
- **US2 (Phase 4)**: after Phase 2; independent of US1 logic but T018 touches scrims.html, so run
  after T011 when working solo. T014 first; T015 → T016 → T017 → T018.
- **US3 (Phase 5)**: after US2 (extends scrim_detail.html and its test file). T019/T020 parallel
  first; T021 → T022 → T023.
- **Polish (Phase 6)**: after all desired stories.

### User Story Dependencies

- **US1 (P1)**: standalone once Phase 2 is done — the MVP.
- **US2 (P2)**: independently testable (detail page reachable by URL even without US1's links);
  only T018's dashboard linking touches US1's template.
- **US3 (P3)**: builds on US2's detail page; attendance logic itself (T019/T021) is independent.

### Parallel Opportunities

- Phase 2: T002 + T003 + T004 together (different files).
- Each story's test tasks: T007 + T008; T014 (with T007/T008 if staffed); T019 + T020.
- Across stories (multiple developers): after Phase 2, US1 (app/scrims.py, scrims.html) and US2
  (rgl_store usage, new scrim_detail.html) mostly touch different files — coordinate only on
  app/routes/scrims.py and scrims.html.

## Parallel Example: User Story 1

```bash
# Failing tests first, in parallel (different files):
Task: "Extend tests/unit/test_scrims.py with expiry tests"          # T007
Task: "Write tests/integration/test_dashboard.py per contract"      # T008
# Then sequentially: T009 (scrims.py) → T010 (routes) → T011 (template) → T012 (cleanup) → T013 (verify)
```

## Implementation Strategy

**MVP first**: T001–T013 (Setup + Foundational + US1) delivers the combined dashboard with expiry —
fully shippable. **Stop and validate** with tests/integration/test_dashboard.py plus a manual look.
Then US2 (T014–T018) adds the detail/roster page, US3 (T019–T023) adds attendance, each
independently verifiable; T024–T025 close out. Commit after each task or logical group.

---

## Phase 8: User Story 4 - Find any RGL opponent when proposing (Priority: P2)

**Added 2026-07-23** via `/speckit-clarify` (spec US4, FR-018..FR-021, SC-006) after US1–US3
shipped. Design: research.md §8–§9, data-model.md US4 tables/queries,
contracts/propose-discovery-routes.md.

**Goal**: The propose form gains a division browser over the current RGL season of the proposing
team's format, backed by a locally cached season directory hydrated in bounded per-request batches
(no threads/schedulers). Every registered team is listed under its division with an
on-platform/off-platform label; off-platform teams are proposable (standard pending proposal with
"they need to join to respond" messaging). The quick pick stays, scoped to on-platform teams.

**Independent Test**: On `/scrims/new`, select your team → division selector shows only that
format's current-season divisions; while hydrating, a "Loaded X of Y teams" note shows and each
request fetches at most the configured batch; pick a division → all its teams appear labeled, own
team unselectable; propose to an off-platform team → normal pending (withdrawable) proposal that
an unrelated user cannot accept; kill RGL (mock) → browser degrades to a notice, quick pick keeps
working and never lists off-platform teams.

- [X] T029 [US4] Add `rgl_seasons` and `rgl_season_teams` tables to `SCHEMA` in app/db.py per specs/004-scrims-dashboard/data-model.md (US4 tables — new tables only, no ALTERs)
- [X] T030 [P] [US4] Add `RGL_DIRECTORY_TTL_SECONDS` (default 86400) and `RGL_HYDRATE_BATCH` (default 20) to app/config.py alongside the roster TTL
- [X] T031 [P] [US4] Write failing unit tests in tests/unit/test_rgl_season.py (mirror test_rgl_roster.py mocking style): `fetch_season` parses the verified `/v0/seasons/{id}` shape (name, formatName → `sixes|highlander|prolander`, `divisionSorting` map, `participatingTeams` ids) and maps 404/timeout/malformed to outcomes; `fetch_team_summary` parses team name/tag/divisionId/divisionName; store: `ensure_season` TTL + stale-if-error; `hydrate_season_teams` hydrates at most `batch` pending rows (assert fetch call count), upserts into `rgl_teams`, leaves failed hydrations pending; `division_browser` groups by division and orders by `division_sorting` rank; `platform_teams` returns only membership-backed same-format teams
- [X] T032 [US4] Implement `fetch_season(season_id)` and `fetch_team_summary(team_id)` (outcome dataclasses, 5 s timeout, never raises) in app/rgl.py; make T031's client tests pass
- [X] T033 [US4] Implement the directory store in app/rgl_store.py: `ensure_season(season_id)`, `hydrate_season_teams(season_id, batch)` (upsert `rgl_teams` + stamp `rgl_season_teams.hydrated_at`/`division_id`), `division_browser(season_id, division_id=None)` (hydrated divisions ordered by sort rank; a division's teams with on-platform flags), `platform_teams(format_)`; make all T031 tests pass
- [X] T034 [P] [US4] Write failing integration tests in tests/integration/test_propose_discovery.py per contracts/propose-discovery-routes.md: division selector lists only the proposing team's season divisions; per-request hydration call-count + "Loaded X of Y" progress note; division team list with correct on/off-platform labels and own team unselectable; `opponent_id` pre-selects the opponent; off-platform proposal → 302, `pending` row, outgoing awaiting-join note, withdraw works, unrelated linked user accept → 403; season fetch failure cold → notice + quick pick still works; failure warm → stale directory browsable; quick pick never contains off-platform teams after full hydration
- [X] T035 [US4] Extend `GET /scrims/new` in app/routes/scrims.py: read `team_id`/`division_id`/`opponent_id` params, resolve the proposing team's `season_id`, call `ensure_season` + `hydrate_season_teams(RGL_HYDRATE_BATCH)`, pass browser context (divisions, selected division's labeled teams, hydrated/total counts, RGL-down flag); switch `_propose_form_context` from `all_teams()` to `platform_teams()`
- [X] T036 [US4] Rework app/templates/scrim_new.html: division selector (GET form preserving `team_id`), division team list grouped under division names with on-platform / "not on the platform yet" labels, select-as-opponent links (own team rendered unselectable), "Loaded X of Y teams — refresh to load more" note, RGL-unavailable notice, kept quick-pick dropdown, `opponent_id` preselection
- [X] T037 [US4] Off-platform proposal messaging: add an opponent-on-platform flag to the scrim queries in app/scrims.py (EXISTS on `rgl_memberships`), show the "waiting for this team to join the platform" note on outgoing items in app/templates/scrims.html, and adjust the propose success flash in app/routes/scrims.py when the opponent is off-platform
- [X] T038 [US4] Checkpoint: run tests/unit/test_rgl_season.py + tests/integration/test_propose_discovery.py, then the full suite — all green, no regressions vs the 156-test baseline
- [X] T039 [US4] Manual validation: quickstart.md step 7 against live RGL (hydration progress over refreshes, division grouping, labels, off-platform propose + withdraw, quick-pick scoping)

**Checkpoint**: Propose flow works against the whole current RGL season, not just on-platform teams.

### US4 Dependencies & Parallel Opportunities

- T029 → T033 (schema before store); T030 + T031 parallel with T029 (different files); T032 → T033
  (client before store); T034 parallel with T031/T032/T033 (separate test file); T035 → T036 →
  T037 sequential-ish (routes → template → messaging; T037 also touches app/scrims.py, safe after
  T035); T038/T039 last.
- US4 is independent of US1–US3 code paths except `scrim_new.html`/`routes/scrims.py` (shared with
  the propose flow) — no other story's files change.

---

## Notes

- 36 tasks: Setup 1 · Foundational 5 · US1 7 · US2 5 · US3 5 · Polish 2 · UI adjustments 3 ·
  US4 11 (T029–T039, added 2026-07-23).
- RGL is always mocked in tests (003 convention); the live endpoint shapes were verified during
  research (research.md §1 rosters, §8 seasons — no divisions/search/bulk endpoints exist).
- Timestamps stay ISO-8601 UTC strings; comparisons are lexicographic — never introduce another
  format.
- The scrims area keeps `@login_required` + `@rgl_link_required` on every new route (FR-008).
