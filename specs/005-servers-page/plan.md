# Implementation Plan: The Servers Page

**Branch**: `005-servers-page` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-servers-page/spec.md`

## Summary

Turn the Servers page from a 001-era placeholder built around self-service `+ Create server` into the
real paid surface: a team sees the servers it is entitled to, buys **credits** (hours of server
runtime) by trading Mann Co. Supply Crate Keys to the operator, spends them on a scrim while
scheduling it, and extends a running server when a match overruns.

**Payment, credits, and the request loop are real and persisted. Server provisioning stays
simulated.** The money path gets proven end-to-end before any MetalLB/RCON work begins, which is
exactly the ordering the constitution's build order asks for.

Technical approach, from [research.md](./research.md):

- A narrow `app/steam_trade.py` seam over `IEconService`, mocked in tests, holding no business rules.
- Crediting is **exactly-once by database constraint** (`UNIQUE (method, provider_ref)` on the Steam
  `tradeofferid`), not by poller discipline.
- Balances are **derived from an append-only ledger** — no cached total that could disagree with it.
- Polling and window expiry run as **CLI commands driven by Kubernetes CronJobs**, never an
  in-process scheduler, because Gunicorn's two sync workers would race on crediting the same trade.
- One prerequisite: **SQLite needs WAL, a busy timeout, and foreign keys** before a background writer
  exists at all.

## Technical Context

**Language/Version**: Python 3.12 (container `python:3.12-slim`; local venv 3.12.3)

**Primary Dependencies**: Flask 3.0.3, requests 2.32.3, gunicorn 22.0.0. **No new runtime
dependencies** — notably no scheduler library (research R5) and no Steam SDK; `requests` against
documented HTTP endpoints is sufficient.

**Storage**: SQLite via stdlib `sqlite3` (`app/db.py`), file at `DB_PATH`, PVC-mounted in cluster.
Five new tables, all additive `CREATE TABLE IF NOT EXISTS` — no `ALTER TABLE` migration path needed.

**Testing**: pytest 8.2.2. Steam is mocked at the `app/steam_trade.py` seam; no network in tests, no
API key needed — matching how RGL and Steam OpenID are already handled.

**Target Platform**: Linux; bare-metal `mke` Kubernetes cluster, Gunicorn 2 sync workers, non-root.

**Project Type**: Server-rendered web application (Flask blueprints + Jinja templates). No frontend
build step; no JS framework. Time rendering continues to go through `app/timefmt.py`.

**Performance Goals**: Not throughput-bound — tens of teams, hundreds of scrims. The one real
constraint is **extension latency**: SC-010 requires buying 30 more minutes in under 15 seconds and
at most two interactions, mid-match. That means extension must be a synchronous local ledger write
with **no Steam call in its path**.

**Constraints**:
- Steam Web API: 100,000 calls/day. A 60s poll is ~1,440/day (~1.4%).
- Crediting is eventually-consistent, bounded by the CronJob interval. The UI must state payment
  states honestly rather than implying instant credit.
- SQLite single-writer: WAL + busy timeout required before the poller exists (research R6).
- `STEAM_API_KEY` becomes load-bearing where it was previously optional.

**Scale/Scope**: ~5 new templates/partials, ~6 new routes, 2 removed, 3 changed scrim routes, 5 new
tables, 2 CLI commands. 226 existing tests must stay green except the one deliberate break below.

## Constitution Check

*Gate against [constitution v3.1.0](../../.specify/memory/constitution.md). Re-checked post-design.*

| Principle | Verdict | Evidence |
|---|---|---|
| **I. Scrims First, Servers as the Upsell** | **PASS** | Scheduling is never blocked by payment: the scrim is created unconditionally *before* any credit work, and a failed reservation leaves a valid serverless scrim (contracts, FR-054, SC-014). The free surface is untouched. |
| **II. Servers Are Cattle** | **PASS (partial scope)** | Runtime window with absolute boundaries, one grace per server, terminal `stopped`. Real reclamation of workload/Service/PVC/IP is feature 006 — this increment simulates it, per the spec's declared scope. |
| **III. Kubernetes-Native Control** | **PASS** | No cluster calls this increment. Scheduled work is a k8s CronJob, not a shelled-out cron or an in-process timer. |
| **IV. Secure by Default** | **PASS** | Steam OpenID §11.1 verification already landed (`ae96163`). No card/bank data; payment completes on Steam. `STEAM_API_KEY` and `OPERATOR_TRADE_URL` come from the secret store, are never logged, never sent to a client. RCON password never stored on the server row nor placed in a template context (FR-009, SC-009). Escrow pre-check fails **closed**. |
| **V. Reproducible Images** | **PASS** | No image changes; no new dependencies. |
| **VI. Everything as Code** | **PASS** | New CronJob manifests land in `deploy/`; config keys documented; no manual cluster steps. |
| **VII. Right-Size the Blast Radius** | **PASS** | Placement failure is a first-class visible state (`failed`, `stopped_reason`) and **returns credits** (FR-067) — a team is never charged for a server it did not get. The concurrency cap itself lands with real provisioning in 006. |
| **VIII. Free to Schedule, Approved to Provision** | **PASS** | Free accounts hold no credits and get the whole scrim surface. Credits are the entitlement unit, enforced server-side, derived from a ledger, never inferred from client input. Granting happens only on observed `Accepted` (3). Credit-spending actions are not offered when unaffordable — *and* are re-checked server-side, since an un-rendered action is not a security control. |

**No violations. Complexity Tracking is therefore empty.**

Two things worth recording rather than hiding:

1. **A deliberate breaking change.** Removing `/servers/new` contradicts feature `001`'s spec (US1,
   US2) and breaks `test_create_server_form_renders`. This is not a regression: under Principle VIII
   there is no user-completable path to self-service creation, so the form promises an action nobody
   can take. The test is replaced by one asserting the route and nav entry are gone.

2. **Principle II is only partly satisfiable this increment**, by the spec's own design. The `[sim]`
   tags mark exactly which requirements are simulated, so 006 has an explicit list rather than an
   archaeology exercise.

## Project Structure

### Documentation (this feature)

```text
specs/005-servers-page/
├── plan.md                       # This file
├── spec.md                       # 82 FRs, 14 SCs, 5 user stories
├── research.md                   # Phase 0 — Steam API verification, architecture decisions
├── data-model.md                 # Phase 1 — 5 new tables, 2 state machines
├── contracts/
│   ├── servers-routes.md         # HTTP + CLI contracts
│   └── steam-trade-client.md     # The Steam economy API seam
├── quickstart.md                 # Phase 1 — end-to-end validation guide
├── checklists/requirements.md    # 16/16
└── tasks.md                      # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
app/
├── db.py                    # CHANGED: WAL + busy_timeout + foreign_keys; 5 new tables
├── models.py                # CHANGED: SAMPLE_SERVERS list → persisted servers; keep can_access
├── steam.py                 # unchanged (OpenID + persona)
├── steam_trade.py           # NEW: IEconService seam — hold durations, received offers
├── credits.py               # NEW: ledger service — grant/reserve/release/spend/extend, balances
├── payments.py              # NEW: payment state machine, item counting, escrow pre-check
├── servers_store.py         # NEW: server persistence + lifecycle transitions
├── cli.py                   # NEW: poll-payments, reconcile-servers
├── scrims.py                # CHANGED: optional credit attach on propose/listing/claim
├── routes/
│   ├── servers.py           # CHANGED: real inventory; extend; new_server REMOVED
│   ├── credits.py           # NEW: /credits, /credits/trade/start
│   ├── account.py           # CHANGED: trade-link capture beneath RGL linking
│   ├── scrims.py            # CHANGED: use_credits; server state + extend on detail
│   └── console.py           # CHANGED: refuse when not running
└── templates/
    ├── servers_list.html    # CHANGED: inventory, balance, price, empty state
    ├── server_detail.html   # CHANGED: time remaining, extend, grace warning
    ├── server_new.html      # REMOVED
    ├── credits.html         # NEW: balance + ledger
    ├── account.html         # CHANGED: trade link section
    ├── base.html            # CHANGED: remove "+ Create server" nav CTA
    ├── dashboard.html       # CHANGED: remove create link; show balance
    └── scrim_detail.html    # CHANGED: server state + extend action

deploy/
├── cronjob-poll-payments.yaml     # NEW
└── cronjob-reconcile-servers.yaml # NEW

tests/
├── unit/
│   ├── test_steam_trade.py   # NEW: param shapes, state mapping, item counting
│   ├── test_credits.py       # NEW: ledger arithmetic, no-negative invariant
│   └── test_payments.py      # NEW: state machine, exactly-once, fail-closed
└── integration/
    ├── test_credits_flow.py  # NEW: pay → poll → credit → attach → extend → expire
    ├── test_servers.py       # NEW: inventory, access, extend gating
    └── test_routes.py        # CHANGED: /servers/new gone
```

**Structure Decision**: The existing flat `app/` layout with a thin service layer per domain
(`scrims.py`, `rgl_store.py`, `accounts.py`) and blueprints under `app/routes/` is kept as-is. New
domains follow the same shape rather than introducing a package hierarchy — the codebase is ~20
modules and the established pattern is legible. `steam_trade.py` is deliberately separate from
`steam.py`: OpenID and the economy API share a vendor and nothing else, and keeping them apart is what
lets tests mock payment without touching authentication.

## Implementation Sequencing

Ordered so each step is independently verifiable and the risky money logic lands on proven ground.

| # | Step | Why here | Requirements |
|---|---|---|---|
| 0 | SQLite pragmas (WAL, busy_timeout, foreign_keys) | Prerequisite. A background writer against today's settings produces `database is locked`, surfacing as dropped payments. Own commit, own test. | research R6 |
| 1 | Schema + `credits.py` ledger with the no-negative invariant | Pure arithmetic, no I/O, fully unit-testable. Everything else builds on it. | FR-059–FR-070 |
| 2 | `steam_trade.py` + unit tests against mocked responses | Isolates the verified signatures before any logic depends on them. | research R1–R4 |
| 3 | Trade link capture on the Accounts page | Hard precondition of the escrow pre-check — nothing downstream works without it. | FR-044–FR-047 |
| 4 | `payments.py` + `flask poll-payments` | The money path. Exactly-once and fail-closed proven here. | FR-032–FR-043, FR-049–FR-051 |
| 5 | `servers_store.py` + windows + `flask reconcile-servers` | Needs credits to reserve and spend. | FR-060–FR-062, FR-072–FR-079 |
| 6 | Servers page rebuild; remove `/servers/new` and both nav entries | Now has real data to render. | FR-001–FR-014, FR-071 |
| 7 | Extend, from both the server page and the scrim page | The SC-010 latency path — local write only, no Steam call. | FR-063–FR-066, FR-080, FR-081 |
| 8 | `use_credits` on propose / post-listing / claim | Last, because it touches the free scheduling path and must not endanger it. | FR-052–FR-058 |
| 9 | `deploy/` CronJobs + seed script extension | Operational surface, once behaviour is settled. | research R5 |

**Step 0 and step 8 are the two that can break existing behaviour** — 0 touches every database
connection, 8 touches the free scheduling path that features 003/004 proved. Both need the full
226-test suite green, and step 8 needs an explicit test that scheduling still succeeds with a zero
balance, an unreachable Steam, and a missing API key.

## Complexity Tracking

No constitutional violations. Table intentionally empty.
