# Implementation Plan: Durable Multi-Writer Metadata Store

**Branch**: `006-postgres-datastore` | **Date**: 2026-07-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-postgres-datastore/spec.md`

## Summary

Replace the single-file SQLite store with **PostgreSQL 17**, reached through **psycopg 3**,
running as a single-instance StatefulSet in `mke` with scheduled `pg_dump` backups and a
rehearsed restore. The store starts **empty** — no data is carried across — and **no
user-facing behavior changes**.

Technical approach, from [research.md](./research.md):

- **psycopg 3 with `dict_row`**, chosen because `Connection.execute()` returns a cursor —
  the exact call shape all 167 existing sites already use. No ORM, no dialect abstraction
  (FR-025 forbids one, and Principle I says the smallest design that works wins).
- **The translation is mechanical**: `?` → `%s`, `lastrowid` → `RETURNING id`,
  `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING`. The 8 existing `ON CONFLICT … excluded`
  upserts are already Postgres syntax and carry over untouched.
- **Timestamps stay `text` and flags stay integer** — deliberately. Both protect FR-001 and
  SC-007; converting types is a clean follow-up, not something to bundle into an engine swap.
- **Ordered `.sql` migrations** applied by a small in-repo runner under a `pg_advisory_lock`,
  so several app copies starting at once initialise exactly once (FR-015, FR-019).
- **One real piece of engineering, and it is the reason this plan is not a find-and-replace**:
  three guarantees currently rest on SQLite's global write lock and break under a genuinely
  concurrent engine.

### The three things that stop being true for free

| What | Today | Under Postgres |
|---|---|---|
| **`credits._spend` cannot overdraw** (FR-013) | Its docstring says "one statement cannot interleave with itself" — true only because SQLite has one global writer | Two concurrent spends both read the pre-spend balance and both insert. **The balance goes negative.** Fixed by a per-account `SELECT … FOR UPDATE` (research R9) |
| **A reservation and its server commit together** (FR-012) | `attach_to_scrim` commits the server, then reserves, then deletes on failure — two transactions | One `transaction()` block |
| **First sign-in cannot double-insert** (FR-014) | `upsert_on_login` reads then writes; SQLite's serialized writer made the race nearly unreachable | Two app copies make it reachable. Becomes `ON CONFLICT … DO UPDATE` |

The first is money-adjacent and silent: a negative balance produced by paid compute, arriving
as a page that looks fine. It is the finding that shapes the sequencing below.

## Technical Context

**Language/Version**: Python 3.12 (container `python:3.12-slim`; local venv 3.12.3)

**Primary Dependencies**: Flask 3.0.3, requests 2.32.3, gunicorn 22.0.0 — unchanged. **Two
new runtime dependencies**: `psycopg[binary]` 3.2.x and `psycopg-pool` 3.2.x (pin exact
patches at implementation). `[binary]` ships libpq as a wheel, so the `python:3.12-slim` deps
stage needs no build toolchain. No ORM, no migration framework, no scheduler library.

**Storage**: PostgreSQL 17, single-instance StatefulSet with a PVC in `mke`. Reached only
through `app/db.py` (FR-023). 14 tables plus `schema_migrations`; **no new entities** — the
existing schema is transcribed, not redesigned.

**Testing**: pytest 8.2.2 against a **real PostgreSQL** — one engine everywhere (FR-025).
Migrations apply once per session; `TRUNCATE … RESTART IDENTITY CASCADE` between tests
(FR-027). Steam and RGL stay mocked exactly as they are.

**Target Platform**: Linux; bare-metal `mke` (Flannel CNI). **2 app replicas** × Gunicorn 2
sync workers, non-root, `readOnlyRootFilesystem`.

**Project Type**: Server-rendered web application (Flask blueprints + Jinja). No frontend
build step. Unchanged by this feature.

**Performance Goals**: Not throughput-bound — low hundreds of teams, a few thousand accounts.
The one latency constraint carried forward is feature 005's SC-010: **buying 30 more minutes
mid-match in under 15 seconds**. The new per-account row lock sits directly in that path, so
the locked region must contain no network I/O — it does not.

**Constraints**:
- **FR-001 dominates.** No user-facing behavior may change. This rules out bundling
  `timestamptz`/`boolean` conversions into the migration (research R5, R6).
- **One engine everywhere** (FR-025) — running tests now requires a local store.
- Connection budget: 2 pods × 2 workers × pool 4 + CronJob peaks ≈ 20, against a default
  `max_connections` of 100.
- Postgres is strictly typed where SQLite coerced; route boundaries must coerce (research R8).
- The cutover may take one brief planned interruption — for this cutover only.

**Scale/Scope**: 25 files containing SQL · 167 `execute()` sites · ~461 placeholders · 11
`lastrowid` reads · 14 tables · 5 new manifests, 3 changed, 1 deleted · **408 existing tests
must stay green**, with only the SQLite-pragma assertions in `tests/unit/test_db.py` replaced
by behavioral equivalents.

## Constitution Check

*Gate against [constitution v4.0.0](../../.specify/memory/constitution.md). Re-checked
post-design.*

| Principle | Verdict | Evidence |
|---|---|---|
| **I. Scrims First, Servers as the Upsell** | **PASS** | FR-001: the free scrim surface behaves identically. Scheduling is not made to depend on anything new — the store was always a hard dependency; it is now one that survives two writers. |
| **II. Servers Are Cattle** | **PASS (not engaged)** | No change to server lifecycle, windows, grace, or reclamation. The reconciler that advances those states can now run concurrently with the web app without contending, which makes the existing lifecycle more reliable, not different. |
| **III. Kubernetes-Native Control** | **PASS** | The store is Kubernetes objects declared in this repo; backups are a CronJob. No container is mutated by hand to reach its desired state. See note 2 below on the operator restore path. |
| **IV. Secure by Default** | **PASS** | `DATABASE_URL` comes from OpenBao via the existing Secret, is never committed, logged, or sent to a client; DSNs are redacted to `host:port/db` in logs and readiness output. `servers` still carries **no** administrative password column, and must not gain one. Authority rules (FR-002) are untouched. See note 3 below on backups. |
| **V. Reproducible Images** | **PASS** | Game-server image untouched. App image gains two pinned wheels; the multi-stage build is unchanged. `postgres:17-alpine` is pinned by tag and should be pinned by digest at apply time. |
| **VI. Everything as Code** | **PASS** | FR-021: every manifest in `deploy/`. FR-019: schema changes are ordered `.sql` files in the repo applied by a recorded mechanism — no hand-editing a live store, which is the specific thing this principle exists to forbid. |
| **VII. Right-Size the Blast Radius** | **PASS** | FR-022: enforced CPU and memory limits on the store so it cannot starve the node or other tenants of the shared cluster. ClusterIP only — the store is never publicly exposed. Connection count is budgeted rather than assumed. |
| **VIII. Free to Schedule, Approved to Provision** | **PASS, and strengthened** | The credit invariants stop being incidental properties of a single-writer file and become enforced ones: exactly-once granting by unique constraint (unchanged), no-overdraw by row lock (**new**), reservation-with-server atomicity (**new**), balances derived from an append-only ledger (unchanged, FR-013). And "a disputed balance can be explained without the operator's help" is only as good as the ability to get the ledger back — which is User Story 2. |

**No violations. Complexity Tracking is therefore empty.**

Three things worth recording rather than hiding:

1. **This plan fixes bugs that predate it.** The `_spend` race, the `attach_to_scrim` split
   transaction, and the `upsert_on_login` read-then-write are latent today and become live
   under a concurrent engine. Fixing them is in scope because FR-012 and FR-013 are
   requirements of *this* feature — but they are corrections, not new capability, and no
   user-facing behavior changes as a result.

2. **The restore path is `kubectl exec`, deliberately.** Principle III governs the *control
   plane* — the app must drive the cluster through the Kubernetes API rather than shelling
   out. Restore is an operator action that the spec explicitly keeps manual (FR-018, and Out
   of Scope: "Automatic failover of the store; recovery is an operator action"). Automating it
   inside the app would be the thing to justify, not leaving it to the operator.

3. **Backups are a new secret-bearing artifact.** A `pg_dump` contains `steam_trade_links`,
   including `access_token` and full trade URLs. That is not a violation of Principle IV —
   nothing is hardcoded or logged — but it is a surface that did not exist before, and it is
   recorded so the control is deliberate: the backup PVC is operator-only, dumps are not
   copied off-cluster casually, and the RCON/administrative password remains absent from the
   database entirely, so it cannot appear in a dump either.

## Project Structure

### Documentation (this feature)

```text
specs/006-postgres-datastore/
├── plan.md                       # This file
├── spec.md                       # 28 FRs, 8 SCs, 3 user stories, 2 clarifications
├── research.md                   # Phase 0 — 21 decisions; R9 is the load-bearing one
├── data-model.md                 # Phase 1 — type mapping, full DDL, constraint→FR table
├── contracts/
│   ├── store-access.md           # The app/db.py surface, query conventions, transaction rules
│   └── deployment.md             # Manifests, secrets, backup, restore, decommission
├── quickstart.md                 # Phase 1 — 13 validation scenarios incl. restore rehearsal
├── checklists/requirements.md    # Re-run after clarification
└── tasks.md                      # Phase 2 — NOT created by /speckit-plan
```

### Source Code (repository root)

```text
migrations/
└── 0001_initial.sql         # NEW: the whole schema. One file, because the store starts empty

app/
├── db.py                    # REWRITTEN: pool, get_db, close_db, transaction(), migrate(), check()
├── config.py                # CHANGED: DB_PATH removed; DATABASE_URL + pool settings; validate()
├── accounts.py              # CHANGED: %s; upsert_on_login → ON CONFLICT (R19)
├── credits.py               # CHANGED: %s; RETURNING id; _spend takes a per-account row lock (R9)
├── payments.py              # CHANGED: %s; RETURNING id; rollback-path audit
├── servers_store.py         # CHANGED: %s; RETURNING id; attach_to_scrim becomes one transaction
├── scrims.py                # CHANGED: %s; sqlite3.Row annotations → dict
├── rgl_store.py             # CHANGED: %s; COLLATE NOCASE → lower(); IFNULL → COALESCE; INSERT OR IGNORE
├── attendance.py            # CHANGED: %s; sqlite3.Row annotations → dict
└── routes/
    ├── health.py            # CHANGED: /healthz does a store round trip (FR-016)
    └── credits.py           # CHANGED: coerce scrim_id at the boundary (R8)

scripts/
└── seed_demo_team.py        # CHANGED: onto the shared access path; --db becomes a DSN (FR-023)

deploy/
├── postgres-statefulset.yaml      # NEW
├── postgres-service.yaml          # NEW
├── backup-pvc.yaml                # NEW
├── cronjob-backup-postgres.yaml   # NEW (FR-017)
├── deployment.yaml                # CHANGED: replicas 2, RollingUpdate maxUnavailable 0, DATABASE_URL
├── cronjob-poll-payments.yaml     # CHANGED: DATABASE_URL, no PVC mount
├── cronjob-reconcile-servers.yaml # CHANGED: DATABASE_URL, no PVC mount
├── secret.example.yaml            # CHANGED: adds database-url
└── pvc.yaml                       # DELETED (FR-005, SC-008)

tests/
├── conftest.py                    # CHANGED: session migrate + per-test TRUNCATE; preflight (FR-024)
├── unit/test_db.py                # REWRITTEN: migrations, pool, advisory lock; pragma tests → behavioral
└── integration/
    ├── test_concurrency.py        # NEW: FR-008–FR-015 proven against the real engine (FR-026)
    └── test_auth.py               # CHANGED: stop opening its own sqlite3 connection (R20)

Dockerfile                   # CHANGED: DB_PATH, /data, VOLUME, and the chown all removed
README.md                    # CHANGED: local Postgres setup, backup, restore (FR-028)
.gitignore                   # CHANGED: the "SQLite DB lives on a PVC" comment is now false
```

**Structure Decision**: The flat `app/` layout with one service module per domain and
blueprints under `app/routes/` is kept exactly as-is. This feature swaps what is underneath
`app/db.py` and rewrites query text in place; it does not move code between modules or
introduce a package hierarchy. `migrations/` is new at the repository root — a sibling of
`deploy/`, since it is the same kind of thing: declarative state that reaches an environment
through the repo (Principle VI).

`app/db.py` remains the **only** module permitted to open a connection (FR-023), which is why
two modules that currently bypass it are pulled back in.

## Implementation Sequencing

Ordered so the suite becomes the safety net early, the mechanical work happens against a
green baseline, and the concurrency fixes — the only genuinely new logic — land last on
proven ground.

| # | Step | Why here | Requirements |
|---|---|---|---|
| 0 | Deps, local Postgres, `app/db.py` rewrite, `0001_initial.sql`, test harness | Nothing else can be verified until the harness can reach a store and reset between tests. Expect most of the suite red at the end of this step — that is the honest state, not a regression | FR-019, FR-023, FR-024, FR-027, R1/R13/R14/R18 |
| 1 | Mechanical SQL translation, module by module (`accounts` → `rgl_store` → `scrims` → `attendance` → `credits` → `payments` → `servers_store`) | The bulk of the diff, and the least interesting. Done per module so the suite goes green incrementally and a break is attributable | FR-001, FR-003, R2/R3/R4 |
| 2 | Boundary type coercion + post-error rollback audit | Strictness failures surface as 500s in paths tests may not cover; sweep them once, deliberately | R8, R10 |
| 3 | **`_spend` per-account row lock** | The load-bearing fix. Needs a green suite underneath it to be reviewable in isolation | **FR-013**, R9 |
| 4 | `attach_to_scrim` single transaction; `upsert_on_login` upsert | The other two guarantees that stop holding for free | FR-012, FR-014, R19 |
| 5 | `test_concurrency.py` | Proves 3 and 4 against the real engine rather than asserting them. FR-026 requires exactly this | FR-008–FR-015, FR-026 |
| 6 | Readiness round trip, `Config.validate()`, DSN redaction | Small, independent, and needed before anything is deployed | FR-016, FR-020 |
| 7 | Seed script + `test_auth.py` onto the shared access path | Closes FR-023; also makes FR-006 (rebuild demo data) true on the new store | FR-006, FR-023 |
| 8 | Manifests: StatefulSet, Service, backup PVC + CronJob, Deployment `replicas: 2`, both CronJobs, Secret | Operational surface, once behavior is settled | FR-017, FR-021, FR-022, US3 |
| 9 | Decommission the old store; README, backup and restore docs; restore rehearsal | Last, because SC-008 can only be verified once everything else is off SQLite | FR-005, FR-028, SC-005, SC-008 |

**Steps 1 and 3 are the two that can break existing behavior.** Step 1 touches every query in
the codebase; step 3 touches the money path. Both need all 408 tests green before moving on,
and step 3 additionally needs the concurrent-spend test from step 5 — which is why 5 follows
immediately rather than being deferred to a testing phase at the end.

**Step 9 is not optional tidying.** A leftover SQLite file or its volume reachable by any
running process is a second, stale source of truth (FR-005), and SC-008 is the check that it
is gone.

## Complexity Tracking

No constitutional violations. Table intentionally empty.
