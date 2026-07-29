---

description: "Task list for feature 005: the Servers page"
---

# Tasks: The Servers Page

**Input**: Design documents from `/specs/005-servers-page/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md),
[data-model.md](./data-model.md), [contracts/](./contracts/)

**Tests**: Included. `plan.md` names specific test modules and the repo carries 226 passing tests —
tests are part of the deliverable here, not optional.

**Organization**: Grouped by user story so each is independently implementable and testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1–US5, mapping to the user stories in `spec.md`
- **`[sim]`**: Satisfied against simulated server state this increment (see spec's Scope)

## Path Conventions

Flat `app/` layout with blueprints under `app/routes/` and templates in `app/templates/`; tests in
`tests/unit/` and `tests/integration/`. Paths below are repository-relative and exact.

> **Two orderings exist, deliberately.** These phases run in **user-value order** (P1 first, so there
> is a demoable MVP early). `plan.md`'s sequencing table runs in **risk-first order** (ledger and
> payment first, page last). Both are valid; see *Implementation Strategy* for how to pick. The
> dependency rules below hold either way.

---

## Phase 1: Setup (Shared Configuration)

**Purpose**: Configuration surface for everything that follows. No behaviour yet.

- [X] T001 [P] Add payment and credit settings to `app/config.py`: `OPERATOR_TRADE_URL`, `PAYMENT_ITEM_NAME` (default `Mann Co. Supply Crate Key`), `PAYMENT_ITEM_APPID` (default `440`), `PAYMENT_MIN_KEYS` (default `2`), `CREDITS_PER_KEY` (default `2.5`), `CREDIT_MINUTES` (default `60`), `EXTENSION_MINUTES` (default `30`), `GRACE_MINUTES` (default `15`), `PAYMENT_POLL_SECONDS` (default `60`), all env-driven per research R12
- [X] T002 Extend `Config.validate()` in `app/config.py` to fail fast in production when `STEAM_API_KEY` or `OPERATOR_TRADE_URL` is absent — `STEAM_API_KEY` was optional (personas degraded gracefully) and payment makes it load-bearing, so a silent absence must not surface later as a poller that never credits anyone
- [X] T003 [P] Add config tests to `tests/unit/test_config.py` asserting defaults resolve and that production without a payment credential raises

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Storage that every user story reads or writes.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete. T004 in particular is a
prerequisite for correctness, not a nicety — see research R6.

- [X] T004 Set `journal_mode=WAL`, `busy_timeout=5000` and `foreign_keys=ON` on every connection in `app/db.py` (`get_db()` and a shared helper the CLI commands reuse). Today no pragmas are set at all, so SQLite takes a whole-database write lock with a **zero** busy timeout; adding a background writer against that yields `database is locked`, and the symptom would be dropped payments. `foreign_keys` is off by default too, which currently makes every `REFERENCES` clause in `SCHEMA` decorative
- [X] T005 [P] Add `tests/unit/test_db.py` asserting WAL is active, `busy_timeout` is non-zero, `foreign_keys` is on, and that a foreign-key violation now actually raises
- [X] T006 Add the five tables to `SCHEMA` in `app/db.py` per [data-model.md](./data-model.md): `steam_trade_links`, `payments` (with `UNIQUE (method, provider_ref)`), `credit_ledger`, `servers`. All `CREATE TABLE IF NOT EXISTS`, additive only, so `init_schema` stays idempotent and no `ALTER TABLE` path is needed for deployed databases
- [X] T007 Create `app/servers_store.py` with persistence and resolution for servers — `accessible_servers`, `get_accessible_server`, `create_server`, `update_state` — reusing the existing `can_access` rule (owner, or a member of the bound RGL team) so access semantics do not fork
- [X] T008 Rework `app/models.py` to drop the module-level `SAMPLE_SERVERS` list in favour of the persisted table, keeping the `Server` display shape (`slots_display`, `status_label`, `is_online`), the `demo` flag, `can_access`, and `validate_server_settings` intact so existing templates and tests keep working
- [X] T009 [P] Extend `scripts/seed_demo_team.py` to seed demo servers as rows (one running, one stopped, owned by the demo rival team) and to remove them in `--clean`, preserving the honest access test that they belong to somebody else

**Checkpoint**: Storage and access control ready. User stories can begin.

---

## Phase 3: User Story 1 - See the servers I actually have (Priority: P1) 🎯 MVP

**Goal**: A team can find the servers it is entitled to, see their state, and get the details needed
to connect — and cannot see anyone else's.

**Independent Test**: Seed one running and one stopped server for the viewer's team plus one for
another team. Open `/servers`. Both of the viewer's render with state and connect details; the third
is absent and 404s by direct id. Requires no payment, no credits, no scheduling.

### Tests for User Story 1

- [X] T010 [P] [US1] Add `tests/integration/test_servers.py` covering inventory rendering, every lifecycle state having a label, running servers showing address and join password, unknown live state distinguished from stopped, another team's server absent and **404 not 403**, and the empty state naming free scheduling and how to buy
- [X] T011 [P] [US1] Add a test to `tests/integration/test_servers.py` asserting no RCON/administrative password appears anywhere in a server response (FR-009, SC-009)

### Implementation for User Story 1

- [X] T012 [US1] Rewrite `list_servers` and `server_detail` in `app/routes/servers.py` to read persisted servers via `app/servers_store.py`, passing lifecycle state, window boundaries and connect details into the template context
- [X] T013 [US1] **Remove** the `new_server` route from `app/routes/servers.py` — self-service creation has no user-completable path under constitution v3.1.0 Principle VIII, so the form promises an action nobody can take
- [X] T014 [P] [US1] Delete `app/templates/server_new.html`
- [X] T015 [US1] Remove the `+ Create server` `nav-cta` from `app/templates/base.html` (line ~18)
- [X] T016 [US1] Remove the `＋ Create server` link from the Servers box in `app/templates/dashboard.html` (line ~23) and reword the box away from "provisioning isn't built yet"
- [X] T017 [US1] Rebuild `app/templates/servers_list.html`: per-server state badge, map, players/capacity, owning team, address and join password when running, scrim binding and reclaim time for per-scrim servers, `DEMO` labelling retained, and an empty state that states scheduling is free and explains that servers are paid for and granted
- [X] T018 [US1] Update `app/templates/server_detail.html` to show lifecycle state, why a server is not running when it isn't, window boundaries via `app/timefmt.py`, and the scrim it belongs to
- [X] T019 [US1] Replace `test_create_server_form_renders` in `tests/integration/test_routes.py` with a test asserting `/servers/new` no longer resolves and neither the nav nor the dashboard offers it — this is the one deliberate break of feature `001`'s spec, recorded in `plan.md`

**Checkpoint**: US1 fully functional and independently testable. Demoable MVP.

---

## Phase 4: User Story 5 - Buy credits, and buy more time mid-match (Priority: P2)

**Goal**: Keys become credits; credits become server time; a match that overruns can buy 30 more
minutes without leaving the page.

**Independent Test**: From a free account, save a trade link, start a payment, drive
`flask poll-payments` with a mocked accepted 2-key offer, and confirm the balance becomes 5 with a
ledger row explaining it. Then extend a running server and confirm +30 minutes and −1 credit.

**Note**: The largest phase, and the increment's reason for being. US2 depends on it.

### Tests for User Story 5

- [X] T020 [P] [US5] Add `tests/unit/test_credits.py`: ledger arithmetic (`available == SUM(delta)`), grant/reserve/release/spend/extend kinds, and the invariant that available balance can never go negative
- [X] T021 [P] [US5] Add `tests/unit/test_steam_trade.py`: exact request parameters for both endpoints, the full `ETradeOfferState` mapping (research R4), `count_payment_items` scoping by `appid` and ignoring non-matching items, and an offer with a non-empty `items_to_give` counting zero
- [X] T022 [P] [US5] Add `tests/unit/test_payments.py`: state machine transitions, `SteamUnavailable` never producing `failed`, escrow pre-check failing **closed** when hold duration cannot be determined, and crediting only on state `3`
- [X] T023 [P] [US5] Add `tests/integration/test_credits_flow.py` covering the table in [quickstart.md](./quickstart.md) Scenario 4, including **running the poller twice on the same accepted offer and asserting the balance does not double**
- [X] T024 [P] [US5] Add a test to `tests/unit/test_steam_trade.py` asserting the poller issues a **historical** pass and not only `active_only=1` — `Accepted` is terminal and excluded by `active_only`, so a loop with only that flag credits nobody, ever, and does so silently (research R1)

### Implementation for User Story 5

- [X] T025 [US5] Create `app/credits.py`: append-only ledger service with `grant`, `reserve`, `release`, `spend`, `extend`, and a derived `available_credits(steam_id)`. No cached balance column — the ledger is the sole truth (research R8). Every write checks the no-negative invariant inside its own transaction
- [X] T026 [US5] Create `app/steam_trade.py` per [contracts/steam-trade-client.md](./contracts/steam-trade-client.md): `get_trade_hold_duration(steamid64, access_token)` using `steamid_target` + `trade_offer_access_token`, `get_received_offers(...)`, and the pure `count_payment_items(...)`. Raises `SteamUnavailable` on transport failure or `429`. Holds no business rules, so tests mock this module rather than `requests`
- [X] T027 [US5] Add trade-link capture to `app/routes/rgl.py` (which owns `GET /account`): `POST /account/trade-link` parsing `partner` and `token`, rejecting a malformed link per-field without storing, and rejecting a link whose `partner` does not resolve to the signed-in SteamID64 — otherwise the escrow pre-check would answer about a different person
- [X] T028 [US5] Add a trade-link section to `app/templates/account.html` beneath the RGL card, stating why it is wanted: it carries the token the escrow pre-check needs, and it is how items would be returned
- [X] T029 [US5] Create `app/payments.py`: payment state machine per [data-model.md](./data-model.md), the escrow pre-check gate, item sufficiency against configured rules, and `floor(keys × CREDITS_PER_KEY)` conversion. Crediting inserts the `grant` ledger row and sets `complete` in **one transaction**, relying on `UNIQUE (method, provider_ref)` for exactly-once rather than on poller discipline (research R7)
- [X] T030 [US5] Create `app/cli.py` with `flask poll-payments`: an `active_only` pass **and** a historical pass, attribution by `accountid_other + 76561197960265728`, state reconciliation, and non-zero exit on Steam failure with all payment state left untouched
- [X] T031 [US5] Register the CLI commands on the app factory in `app/__init__.py`
- [X] T032 [US5] Create `app/routes/credits.py` with `GET /credits` (balance and ledger) and `POST /credits/trade/start` enforcing the preconditions **in order**: trade link on file → no hold predicted → no payment already `started`; then create the payment row and redirect to Steam without ever rendering the operator's token into the page
- [X] T033 [US5] Register the credits blueprint in `app/__init__.py`
- [X] T034 [P] [US5] Create `app/templates/credits.html`: available balance, the full price (2 keys → 5 credits, 1 credit = 1 hour, extend = 1 credit per 30 min), in-flight payment state including held-with-unknown-expiry, and the ledger with a cause per row
- [X] T035 [US5] Add runtime-window handling to `app/servers_store.py`: `window_starts_at` from the scrim's scheduled time, `window_ends_at`, `grace_used`, and transitions `scheduled → starting → running → in_grace → stopped` with `stopped_reason`
- [X] T036 [US5] Add `flask reconcile-servers` to `app/cli.py`: advance state against the clock, spend reserved credits as a window begins, return them for `cancelled` or `failed`, enter the 15-minute grace once per server, and stop with `stopped_reason = time_expired`. Idempotent — safe to re-run and to run after a missed interval
- [X] T037 [US5] Add `POST /servers/<id>/extend` to `app/routes/servers.py`: owner-only, refused when not `running`/`in_grace`, extends `window_ends_at` by `EXTENSION_MINUTES` for 1 credit, writes an `extend` ledger row. **No Steam call in this path** — that is what makes SC-010's 15-second budget reachable
- [X] T038 [US5] Update `app/templates/server_detail.html`: time remaining, the extend action with its cost and added minutes stated before committing, and a prominent borrowed-time warning while `in_grace`
- [X] T039 [US5] Update `app/templates/servers_list.html` to show the balance and the price, and to render **no credit-spending action at all** when the balance cannot cover one — showing the route to buying credits in its place rather than a disabled control or one that fails on submit
- [X] T040 [US5] Add a test to `tests/integration/test_credits_flow.py` asserting the extend route is still refused **server-side** at zero balance even when posted directly — an un-rendered action is not a security control

**Checkpoint**: Payment loop and extension work end to end against simulated servers.

---

## Phase 5: User Story 2 - Get a server for a scrim, as I schedule it (Priority: P2)

**Goal**: Choosing a server is part of scheduling — on propose, on post-a-listing, and on claim.

**Independent Test**: With 5 credits, propose a scrim with the server option ticked; a server is
attached with its window at the scrim's scheduled time. With 0 credits the option is absent and the
scrim is still created.

**⚠️ Depends on US5** — credits must exist before they can be reserved. This is a genuine dependency,
not an artefact of ordering.

### Tests for User Story 2

- [X] T041 [P] [US2] Add scheduling-attach tests to `tests/integration/test_credits_flow.py`: attach on propose, on post-a-listing and on claim; window starting at the **scrim's scheduled time**; reserved credits released when a listing lapses unclaimed or a scrim is cancelled before start; one server per scrim
- [X] T042 [P] [US2] Add the Principle I guard tests to `tests/integration/test_scrims.py`: scheduling succeeds with a zero balance, with `use_credits` posted anyway, with Steam unreachable, and with `STEAM_API_KEY` unset — in every case the scrim is created and simply has no server. Sits beside the existing `test_no_scheduling_action_provisions_servers`, which asserts the same boundary from the other direction

### Implementation for User Story 2

- [X] T043 [US2] Add optional credit attachment to `app/scrims.py` for proposal, listing and claim creation. The scrim MUST be created **first and unconditionally**; the reservation follows and MUST NOT share a transaction whose failure could abort or roll back the scrim
- [X] T044 [US2] Accept the optional `use_credits` field on `POST /scrims/new`, `POST /scrims/listings/new` and `POST /scrims/<id>/claim` in `app/routes/scrims.py`, ignoring it when the balance cannot cover a server and still creating the scrim
- [X] T045 [US2] Add `POST /scrims/<id>/server/attach` to `app/routes/scrims.py` for attaching to an already-scheduled scrim, returning `409` when that scrim already has one
- [X] T046 [P] [US2] Add the server option to `app/templates/scrim_new.html` and `app/templates/listing_new.html`, rendered only when the balance can cover it, with the cost stated
- [X] T047 [US2] Add the same option to the claim action wherever it is rendered (`app/templates/scrim_detail.html` and the listings view)
- [X] T048 [US2] Update `app/templates/scrim_detail.html` to show the attached server's state, offer the extend action there (FR-080), and — where the option was chosen but never paid for — state plainly that **no server is attached** rather than implying one is coming
- [X] T049 [US2] Handle rescheduling in `app/scrims.py`: a scrim whose time changes moves its server's window with it, consuming and returning nothing

**Checkpoint**: Scheduling and paying are one flow, and scheduling is still free and unbreakable.

---

## Phase 6: User Story 3 - Manage and control a server I have (Priority: P3)

**Goal**: The owner can change what is changeable and issue commands while it runs.

**Independent Test**: As owner of a running server, change map and join password and see them
applied; issue a command and see a response; confirm a non-owner teammate sees neither control.

### Tests for User Story 3

- [X] T050 [P] [US3] Add settings and console tests to `tests/integration/test_servers.py`: settings persist, invalid input rejected per-field with nothing applied, commands refused with a stated reason when not running, and owner-only controls hidden from a non-owner teammate who can still see and join

### Implementation for User Story 3

- [X] T051 [US3] `[sim]` Make `POST /servers/<id>/settings` in `app/routes/servers.py` persist through `app/servers_store.py` instead of discarding, keeping `validate_server_settings` as the per-field gate
- [X] T052 [US3] `[sim]` Make `app/routes/console.py` refuse when the server is not `running`, stating why, instead of always returning a placeholder response
- [X] T053 [US3] Restrict the settings and console surfaces to the owner in `app/routes/servers.py` and `app/routes/console.py`, re-checked server-side, while team members retain visibility and join details
- [X] T054 [US3] Offer only the settings meaningful for a short-lived per-scrim server in `app/templates/server_detail.html`, distinguishing owner controls from what a teammate sees

**Checkpoint**: All three primary stories work independently.

---

## Phase 7: User Story 4 - Terms ending, and servers that could not be placed (Priority: P4)

**Goal**: Nothing vanishes unannounced, and a server that could not be created says so in time.

**Independent Test**: Mark a server `failed`; its team sees the failure against the scrim and the
reserved credits are back on the balance.

### Tests for User Story 4

- [X] T055 [P] [US4] Add failure and term tests to `tests/integration/test_servers.py`: a `failed` server surfaces against its scrim, **its credits are returned** (FR-067), and a stopped-for-time server is distinguishable from a broken one

### Implementation for User Story 4

- [X] T056 [US4] Add the `failed` path to `app/servers_store.py` and `app/cli.py` with `stopped_reason = failed_to_place`, returning reserved credits — a team must never be charged for a server it did not get (Principle VII)
- [X] T057 [US4] Surface placement failure against the scrim in `app/templates/scrim_detail.html` and `app/templates/servers_list.html`, rather than the server simply being absent
- [X] T058 [US4] Render season-term information — term end and what happens at it — in `app/templates/server_detail.html` for servers with no `scrim_id`. Display only: constitution v3.1.0 leaves the season-term purchase unit undefined, so there is no way to create one yet

**Checkpoint**: All user stories independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T059 [P] Add `deploy/cronjob-poll-payments.yaml` invoking `flask poll-payments` on `PAYMENT_POLL_SECONDS`, with `concurrencyPolicy: Forbid` so two pollers can never race on the same trade
- [X] T060 [P] Add `deploy/cronjob-reconcile-servers.yaml` invoking `flask reconcile-servers`, also `concurrencyPolicy: Forbid`
- [X] T061 [P] Document the new configuration and the credit model in `README.md`, and correct the Monetization row and Scope section, which still describe an entitlement as "a per-scrim server" granted by operator approval
- [X] T062 [P] Update `docs/constitution-seed.md`, which predates both v3.0.0 and v3.1.0
- [X] T063 Grep the whole tree for any secret leak — API key, trade token, RCON password — in source, logs, templates and error paths
- [ ] T064 Run every scenario in [quickstart.md](./quickstart.md) by hand against a real browser session
- [X] T065 Confirm the full suite is green: 226 pre-existing tests plus the new ones, less the single deliberately replaced `test_create_server_form_renders`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Setup. **Blocks every user story.** T004 blocks correctness,
  not just progress.
- **US1 (Phase 3)**: Depends on Foundational only. **Fully independent** — the MVP.
- **US5 (Phase 4)**: Depends on Foundational only. Independent of US1, though both render on `/servers`.
- **US2 (Phase 5)**: Depends on Foundational **and US5** — credits must exist to be reserved.
- **US3 (Phase 6)**: Depends on Foundational **and US1** — needs a persisted server to manage.
- **US4 (Phase 7)**: Depends on **US5** (credit return) and benefits from US1's rendering.
- **Polish (Phase 8)**: Depends on all desired stories.

### Story Independence

| Story | Priority | Independent? | Blocking dependency |
|---|---|---|---|
| US1 — see my servers | P1 | **Yes** | none |
| US5 — buy credits, extend | P2 | **Yes** | none |
| US2 — attach while scheduling | P2 | No | US5 |
| US3 — manage and control | P3 | Partly | US1 |
| US4 — terms and failures | P4 | No | US5 |

US1 and US5 can proceed **in parallel** by two people once Phase 2 lands. That is the only genuine
parallel-story opportunity here; the rest chain.

### Within Each Story

Tests before implementation · store before service before route before template · server-side
enforcement before any UI gating (an un-rendered action is not a security control).

### Parallel Opportunities

- T001 and T003 together in Setup.
- T005 and T009 alongside T006–T008 in Foundational.
- **All five US5 test tasks (T020–T024) in parallel** — separate files, no shared fixtures.
- T010 and T011 in parallel; T014 alongside T012–T013.
- T041 and T042 in parallel; T046 alongside T043–T045.
- T059–T062 all in parallel in Polish.

---

## Parallel Example: User Story 5

```bash
# All five test modules are independent files — write them together:
Task: "tests/unit/test_credits.py — ledger arithmetic and the no-negative invariant"
Task: "tests/unit/test_steam_trade.py — request params, state mapping, item counting"
Task: "tests/unit/test_payments.py — state machine, exactly-once, fail-closed"
Task: "tests/integration/test_credits_flow.py — pay → poll → credit → attach → extend → expire"
Task: "tests/unit/test_steam_trade.py — assert the historical pass exists, not only active_only"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 → Phase 2 → Phase 3.
2. **Stop and validate**: seed servers, confirm inventory, access control and 404 behaviour.
3. Demoable. The page is honest for the first time — no button promising an impossible action.

### Value-first vs risk-first

These phases are **value-first**: US1 ships a demoable page before any money logic exists.
`plan.md`'s table is **risk-first**: ledger and payment land before the page, so the hardest thing
(money, exactly-once, escrow) is proven earliest and the page is built against real data instead of
being retrofitted.

- Choose **value-first** if you want something to look at and react to soon. US1 renders seeded rows,
  so it needs no payment at all.
- Choose **risk-first** (Phase 1 → 2 → **4** → 3 → 5 → 6 → 7) if you would rather find out early that
  something about the Steam integration doesn't hold. Recommended for solo work — a page built on a
  payment model that turns out to be wrong is a page rebuilt.

Either way T004 comes first and Phase 5 comes late.

### Incremental Delivery

1. Setup + Foundational → storage ready.
2. US1 → demo the honest page.
3. US5 → the money loop works; a real trade grants real credits.
4. US2 → paying becomes part of scheduling.
5. US3, US4 → management and failure honesty.
6. Polish → CronJobs, docs, secret sweep, quickstart.

---

## Notes

- The two riskiest tasks are **T004** (touches every database connection) and **T043/T044** (touch the
  free scheduling path that features 003 and 004 proved). Both need the full suite green.
- `[sim]` tasks are satisfied against simulated server state. Feature 006 replaces the transitions
  behind the same seam rather than rewriting the page.
- T019 is an intentional break of feature `001`'s spec, justified in `plan.md`'s Constitution Check.
- Commit per task or per logical group; stop at any checkpoint to validate a story on its own.
