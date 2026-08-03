# Phase 0 Research: Durable Multi-Writer Metadata Store

**Feature**: `006-postgres-datastore` · **Date**: 2026-07-30 · **Spec**: [spec.md](./spec.md)

The engine is directed (PostgreSQL, spec Assumptions). What was genuinely open — and what
this document resolves — is how it is reached, how ~167 SQLite call sites move without
changing behavior, which integrity guarantees **stop holding for free** once a real
concurrent engine is underneath, how the store runs and is backed up on `mke`, and how a
test suite that used a throwaway file per test works against a shared server.

The load-bearing finding is **R9**: one existing guarantee is currently held up by
SQLite's global write lock and silently breaks under Postgres. It is money-adjacent.

---

## Baseline: what is actually there

Measured, not assumed:

| Thing | Count | Where |
|---|---|---|
| `execute(` call sites | 167 | 25 files |
| `?` placeholders | ~461 | app, scripts, tests |
| `lastrowid` reads | 11 | `credits`, `scrims`, `payments`, `servers_store`, 5 test files |
| `ON CONFLICT … excluded` upserts | 8 | `rgl_store`, `payments`, `attendance`, seed script |
| `INSERT OR IGNORE/REPLACE` | 7 | `rgl_store`, seed script, 4 test files |
| `sqlite3.Row` type annotations | 22 | `scrims`, `rgl_store`, `attendance` |
| Positional row access (`row[0]`) | 8 | 1 in seed script, 7 in tests |
| Modules opening their own connection | 3 | `app/db.py` (correct), `scripts/seed_demo_team.py`, `tests/integration/test_auth.py` |
| Runtime dependencies | 3 | Flask, gunicorn, requests |

No ORM, no query builder, no SQLAlchemy. Every query is a literal string handed to
`sqlite3`. That is the surface being moved.

---

## R1 — Driver

**Decision: psycopg 3** (`psycopg[binary]`, plus `psycopg_pool`), sync API.

Rationale — one property decides it. psycopg 3 has `Connection.execute(query, params)`
returning a cursor, which is the *exact* call shape this codebase already uses:

```python
get_db().execute("SELECT … WHERE steam_id = %s", (steam_id,)).fetchone()
```

With `row_factory=dict_row`, rows come back as `dict` — mapping access (`row["steam_id"]`),
`dict(row)`, and `{**dict(r), …}` all keep working. So the migration touches placeholders
and a short list of named idioms rather than restructuring 167 call sites.

Alternatives considered:

- **psycopg 2** — no `Connection.execute()`; every site becomes `with conn.cursor() as cur`,
  a far larger and riskier diff. In maintenance mode upstream.
- **asyncpg** — wrong shape entirely. Flask is sync, served by Gunicorn sync workers.
- **SQLAlchemy Core or ORM** — would rewrite every query in the codebase to buy an
  abstraction the spec explicitly does not want (FR-025, and Out of Scope: "no compatibility
  layer, dialect abstraction"). Constitution Principle I: when two designs both work, the
  smallest one wins. Rejected on both counts.

`psycopg[binary]` ships the C library as a wheel, so the container build needs no
`libpq-dev` / build toolchain — the `python:3.12-slim` deps stage stays as it is.

## R2 — Placeholder style

**Decision: mechanically rewrite `?` → `%s` at every site.** ~461 occurrences across 25
files, each one adjacent to the query it belongs to.

Rejected: a shim on the connection that rewrites `?` to `%s` before dispatch. It reads as
magic, breaks on any literal `?` inside a string value, and hides which dialect is in play —
which is the specific confusion FR-025 exists to prevent. A visible `%s` is the honest
signal that this is Postgres.

Note the escaping trap: with `%s` placeholders, any literal `%` in a query (e.g. a `LIKE`
pattern) must be `%%` **only if** the string is also being `%`-formatted. This codebase
builds `LIKE` patterns as *parameters* (`app/rgl_store.py:328` passes `like` as a bound
value), so no query text contains a literal `%`. One f-string query exists
(`payments.recent_payments`, interpolating a constant SELECT prefix) — it interpolates SQL
text, not values, and is safe.

## R3 — Row identity after insert

**Decision:** `cur.lastrowid` → `RETURNING id` + `fetchone()["id"]`. 11 sites.

psycopg 3 does not provide a meaningful `lastrowid`. `RETURNING` is the Postgres idiom, is
race-free by construction, and costs no extra round trip. `cursor.rowcount` — which
`credits._spend` and `payments._claim_offer` both depend on — behaves identically and needs
no change.

## R4 — Upserts and conflict handling

**`ON CONFLICT (col) DO UPDATE SET x = excluded.x` is Postgres syntax already.** SQLite
borrowed it. All 8 existing upserts carry over verbatim — the single largest piece of luck
in this migration.

What changes:

- `INSERT OR IGNORE` → `INSERT … ON CONFLICT DO NOTHING` (7 sites, 6 of them in tests/seed).
- `INSERT OR REPLACE` → `ON CONFLICT (…) DO UPDATE` (1 site, `test_server_access.py:43`).
  Not a literal equivalent — `OR REPLACE` deletes and reinserts, `DO UPDATE` updates in
  place — but the call site only ever rewrites the same row's columns, so behavior matches.

## R5 — Timestamps stay `text`

**Decision: store timestamps as `text`, not `timestamptz`.** Deliberate, and the single
biggest "why didn't you do it properly" question this plan will attract, so the reasoning is
recorded in full.

Every timestamp in this app is an ISO-8601 UTC string produced by
`datetime.now(timezone.utc).isoformat()`. They are compared **lexicographically** in both
places they are compared:

- in SQL — `WHERE scheduled_at >= ?`, `ORDER BY scheduled_at` (scrims, listings, dashboard)
- in Python — `scheduled <= utc_now()` in `payments._annotate`, `scrim["scheduled_at"][:10]`
  string-slicing in `servers_store.attach_to_scrim`

For ISO-8601 UTC with a fixed offset, lexicographic order *is* chronological order, so both
are correct today. Moving to `timestamptz` would make psycopg return `datetime` objects,
which would break the string slice, change every `timefmt.py` filter input, alter what ~26
test files assert, and change what renders on the page — in a feature whose **first
requirement (FR-001) is that nothing user-facing changes**.

The engine swap is already the largest change this codebase has taken. Coupling a semantic
type change to it converts a mechanical, reviewable migration into a behavioral one, and
puts SC-007 (identical before/after walkthrough) at risk for no requirement in this spec.

Recorded as deliberate debt: converting to `timestamptz` is a clean, well-scoped follow-up
once parity is proven, and is strictly easier *after* the engine move than during it.

Alternative considered — `timestamptz` now: rejected above. Sorting and comparison semantics
are identical either way for this data, so nothing in FR-001–FR-028 is unmet by `text`.

## R6 — Booleans stay integer

**Decision: `is_verified`, `is_banned`, `is_on_probation`, `is_leader`, `grace_used`, `demo`
become `smallint`, not `boolean`.**

Same reasoning as R5, smaller stakes. The app writes `int(profile.is_verified)` and reads
`bool(p["is_leader"])`; SQL does `ORDER BY is_leader DESC` and `WHERE grace_used`. Integer
columns keep all of that literally unchanged. `boolean` would work too but requires auditing
every write and every ordering for no behavioral gain in this feature.

## R7 — Identity columns, and a sequence trap

**Decision:** `INTEGER PRIMARY KEY AUTOINCREMENT` → `integer GENERATED BY DEFAULT AS IDENTITY`.

**`BY DEFAULT`, not `ALWAYS`** — because existing tests insert explicit ids
(`tests/unit/test_db.py:149` inserts `scrims (id, …) VALUES (1, …)`), and `ALWAYS` rejects
that outright.

The trap: an explicit-id insert does **not** advance the identity sequence. Insert id 1 by
hand, then let the next insert auto-generate, and it also tries 1 → unique violation. SQLite's
`AUTOINCREMENT` has the same hazard but tests never hit it, because each test got a fresh
file and rarely mixed both styles.

Mitigation, in order of preference:
1. Per-test `TRUNCATE … RESTART IDENTITY` (R18) resets sequences between tests, so the blast
   radius is one test.
2. Tests that insert explicit ids and *then* rely on auto-generation must stop doing one or
   the other. There are few; the audit is a task.

## R8 — Postgres is strictly typed; SQLite was not

SQLite coerced `'5'` into an `INTEGER` column silently. Postgres refuses: passing a Python
`str` where the column is `integer` raises `DatatypeMismatch`.

One confirmed live site: **`app/routes/credits.py:42`**

```python
scrim_id = request.form.get("scrim_id") or None      # str
payments.start_payment(steam_id, target_scrim_id=scrim_id)
# → INSERT INTO payments (… target_scrim_id …)   -- integer column
```

Works today by coercion; raises under Postgres. Most other routes already coerce at the
boundary (`app/routes/scrims.py:64` does `int(request.form.get(name, ""))`) and Flask's
`<int:…>` converters handle 14 more. The full boundary audit is a task, not a research
question — but it is a *class* of latent bug this migration surfaces rather than introduces,
and the strictness is an improvement worth stating plainly.

## R9 — The credit-spend race (the finding that matters)

**`credits._spend` is correct today only because SQLite has one global writer. Under
Postgres it is a live race that can drive a balance negative.**

The current statement:

```sql
INSERT INTO credit_ledger (…)
SELECT ?, ?, ?, …
WHERE (SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE steam_id = ?) >= ?
```

Its docstring says "One statement cannot interleave with itself." That is true under
SQLite, where every write serializes globally. Under Postgres at READ COMMITTED, two
concurrent transactions spending the same account's last credit both evaluate the `WHERE`
against a snapshot taken before either insert, both see a sufficient balance, and both
insert. The account goes to −1.

This is exactly the kind of failure the spec calls out as silent and money-adjacent, and
FR-013 forbids the obvious dodge (a cached balance column with a `CHECK`).

**Decision: serialize spends per account with a row lock.** Inside the same transaction,
before the conditional insert:

```sql
SELECT 1 FROM users WHERE steam_id = %s FOR UPDATE
```

Then the existing conditional insert, then commit. The `users` row always exists — every
`credit_ledger.steam_id` is a foreign key to it — so the lock always has a target.

Why this one:
- **Per-account.** Two different users spending simultaneously never touch each other's lock,
  which is what FR-008 requires (no writer waiting on an unrelated writer).
- The lock is held for the length of one tiny transaction with no network I/O in it —
  `spend_extension` is explicitly the mid-match latency path (SC-010 from feature 005) and
  stays a pure local write.
- It is released by commit/rollback automatically. No leak path.

Alternatives considered:

| Option | Why rejected |
|---|---|
| `SERIALIZABLE` isolation + retry | Correct, but every write path in the app needs a retry protocol, and contention surfaces as `SerializationFailure` errors that must be caught everywhere. Large blast radius for one invariant. |
| `pg_advisory_xact_lock(hashtext(steam_id))` | Works, but a 64-bit hash of an arbitrary string invites collisions between unrelated accounts — reintroducing exactly the unrelated-writer contention FR-008 forbids. |
| Cached balance column + `CHECK (balance >= 0)` | Directly violates FR-013 and constitution VIII: the balance must be derivable from the ledger, never a stored total that can disagree with it. |
| Leave it; accept the race | The failure is a negative balance produced by paid compute. Not acceptable. |

**FR-026 requires this be proven by test**, not asserted: a test that fires N concurrent
spends at a balance of 1 and asserts exactly one succeeds and the balance never goes below 0.

## R10 — Exactly-once crediting carries over

`UNIQUE (method, provider_ref)` is the guarantee (FR-009), and it transfers unchanged. Both
engines treat `NULL` as non-colliding in a unique constraint, which is what lets many
`provider_ref IS NULL` rows coexist while claimed offers stay unique — so
`payments._claim_offer`'s conditional `UPDATE … WHERE provider_ref IS NULL` + `rowcount == 1`
check keeps working exactly as written.

**One Postgres-specific hazard:** a failed statement aborts the whole transaction. Any
subsequent statement on that connection raises `InFailedSqlTransaction` until a rollback.
SQLite let you carry on after an error.

Audited: `payments._complete` and `payments._claim_offer` already wrap in
`try/except: db.rollback(); raise`, and `credits._spend` rolls back before re-reading. Those
are correct as-is. The audit for *unrolled-back* except paths across the codebase is a task.

## R11 — One server per scrim carries over

```sql
CREATE UNIQUE INDEX … ON servers(scrim_id) WHERE scrim_id IS NOT NULL
```

Postgres supports partial unique indexes with identical syntax and semantics. FR-010 is met
by the same mechanism, now genuinely enforced under concurrency rather than under a global
write lock.

## R12 — Foreign keys stop being opt-in

SQLite needs `PRAGMA foreign_keys = ON` per connection; it defaults **off**, which is why
feature 005 had to add it and why every `REFERENCES` clause written before that was
decorative. Postgres enforces them always, on every connection, with no way to forget.

FR-011 gets *stronger* for free. `tests/unit/test_db.py::test_foreign_keys_are_enforced`
survives as a behavioral test (insert a ledger entry for a nonexistent account → integrity
error); only its pragma assertion goes.

## R13 — Schema changes: a minimal in-repo migration runner

**Decision:** ordered `.sql` files in `migrations/`, applied by a small runner in `app/db.py`,
recorded in a `schema_migrations` table, guarded by a Postgres advisory lock.

```
migrations/0001_initial.sql        # the whole schema, since the store starts empty (FR-004)
```

The runner, on startup: `pg_advisory_lock(<constant>)` → read applied versions → apply each
missing file in filename order inside its own transaction → record it → unlock.

- **FR-015 (several copies start at once)** is satisfied by the advisory lock: the first pod
  in takes it, the others block briefly and then find every migration already applied. Nobody
  fails to start, and initialisation takes effect exactly once. Naked `CREATE TABLE IF NOT
  EXISTS` from two connections at once can actually collide on Postgres system catalogs, so
  the lock is doing real work, not decoration.
- **DDL in Postgres is transactional**, so a migration that fails halfway leaves nothing
  half-created — a materially better story than the current `executescript`.

Alternatives considered:

- **Alembic** — drags in SQLAlchemy, a large dependency whose ORM this app does not use and
  will not use (R1). The spec asks for "a repeatable, ordered mechanism recorded in the
  repository" (FR-019), which is a page of code, not a framework.
- **A separate migration Job / initContainer** — better hygiene at larger scale, and worth
  revisiting, but it needs deploy-ordering machinery to guarantee it runs before any pod
  serves. In-process + advisory lock is what makes FR-015 true with no extra moving parts.

## R14 — Connections and pooling

**Decision:** one `psycopg_pool.ConnectionPool` per process, lazily opened, connections
checked out per request and returned on teardown — preserving the existing
`get_db()` / `close_db()` shape exactly.

```
min_size=1, max_size=4, check=ConnectionPool.check_connection
```

- Gunicorn runs **2 sync workers**; a sync worker handles one request at a time, so a pool of
  4 per process is generous headroom, not tuning.
- Budget: 2 app pods × 2 workers × 4 + CronJob peaks ≈ 20 connections against Postgres's
  default `max_connections = 100`. Comfortable.
- `check=check_connection` is what handles the spec's **"brief connection interruption"** edge
  case: a connection broken while idle in the pool is discarded and replaced at checkout
  rather than handed to a request. No operator restart, no code change at the call sites.
- `putconn` rolls back any open transaction before returning a connection to the pool, which
  preserves today's semantics (uncommitted work is discarded when the request ends).

The pool must be created **after** fork, not at import — a pool inherited across Gunicorn's
fork would share sockets between workers. Lazy creation on first `get_db()` in each process
handles this without a Gunicorn hook.

## R15 — Where Postgres runs

**Decision: a single-instance StatefulSet in `mke`, in this repository**, with a PVC, a
ClusterIP Service, enforced resource limits, and credentials from OpenBao surfaced as a
Kubernetes Secret.

Image `postgres:17-alpine` (16 equally acceptable — pin one and record it).

This is sized to the spec, which puts **automatic failover, replication, and read replicas
explicitly out of scope** and asks only that recovery be an operator action (FR-018).

Alternatives considered:

- **CloudNativePG (or Zalando) operator** — gives replication, automated failover, and PITR
  to object storage. All three are out of scope per the spec. It also needs an operator
  installed cluster-wide, object storage that is not confirmed to exist on `mke`, and this
  machine has no `helm`. Recorded as the documented upgrade path if PITR is ever required.
- **Managed/external Postgres** — `mke` is bare metal with no cloud provider attached, and
  Principle VI wants cluster state reachable through this repo.
- **A Deployment rather than a StatefulSet** — a StatefulSet gives a stable identity and an
  ordered, one-at-a-time relationship to its volume, which is what you want for the single
  writer that owns the data. A Deployment with `Recreate` would work but expresses less.

**Operational check deferred to implementation, not a spec unknown:** the cluster was not
reachable while planning (VPN down), so the default StorageClass name and its access modes
need confirming before `pvc` manifests are applied. Everything else here is manifest-level.

## R16 — Backup and restore

**Decision:** a `pg_dump -Fc` CronJob writing timestamped dumps to a dedicated PVC, with
retention pruning; restore by `pg_restore` into a fresh database, documented and rehearsed.

- `-Fc` (custom format) rather than plain SQL: compressed, and restorable selectively with
  `pg_restore`.
- **FR-017's second half — "the operator MUST be able to see whether the most recent backup
  succeeded and when"** — is met two ways: the CronJob's Job history is visible
  (`kubectl get jobs -l component=backup`), and each successful run writes a `latest.json`
  marker (timestamp, byte size, dump filename) the operator can read without parsing logs. A
  backup that silently stopped working is the failure mode worth engineering against.
- Retention: keep N daily dumps on the PVC. SC-005 asks to restore to a state **no more than
  24 hours old**, which a daily schedule meets with margin.
- **SC-005 also requires a rehearsal** — restore verified at least once, within 30 minutes.
  The procedure lives in `quickstart.md` as runnable steps, so the rehearsal is a script to
  follow rather than an improvisation during an incident.

Alternative considered — **continuous archiving / PITR (WAL shipping)**: needs object storage,
and the spec's own target is 24-hour recovery. Out of proportion to the requirement.

## R17 — Readiness must actually check the store

**Decision:** `/healthz` performs a `SELECT 1` with a short timeout; failure returns 503 and
logs the error. The `APP_READY` override stays.

Today `/healthz` returns `ok` as long as the process is up — which under the new topology
would let Kubernetes route traffic to a pod that cannot reach the database, serving pages
that look fine and show nothing. FR-016 names this exact failure. Making readiness
store-dependent is the point, not a side effect.

Startup failure is the other half: an unreachable store at boot must fail visibly (the
migration runner cannot acquire a connection → the pod crashes and is restarted, which is
loud) rather than starting a process that serves empty pages.

## R18 — Running tests against a real server

The suite currently gets a **fresh SQLite file per test** via `tmp_path`. That is the
isolation FR-027 requires, and it is free. Against one shared Postgres it has to be
recreated deliberately.

**Decision:** one database for the suite. Migrations applied once per session. Between tests,
`TRUNCATE <every table> RESTART IDENTITY CASCADE`.

Why truncate:
- **Fast** — sub-millisecond against empty/small tables; 226 tests stay quick.
- **`RESTART IDENTITY` resets the sequences**, so tests asserting on specific ids (and the
  explicit-id inserts from R7) behave as they do today with a fresh file.
- **It works with code that commits.** The wrap-each-test-in-a-transaction trick does not: the
  app commits for real, and the test, the app, and background helpers use different
  connections.

Alternatives considered:

- **A database per test from a template** (`CREATE DATABASE … TEMPLATE …`) — cleanest
  isolation, but ~100 ms × 226 tests adds ~25 s to every run.
- **testcontainers-python** — a new dev dependency that requires Docker in every environment
  that runs tests and hides where the store came from. `DATABASE_URL` pointing at a container
  the developer started is more honest and equally reproducible.

**FR-024 explicitly requires a good failure when no store is reachable.** A pytest
session-start hook checks connectivity once and fails with an actionable message naming the
`docker run` command and the `DATABASE_URL` variable — not 226 stack traces that read like
broken tests.

## R19 — Two transaction boundaries that are wrong today

Surfaced while auditing for R9; both are FR-012 ("commit together or not at all") gaps that
SQLite's behavior partially masked.

1. **`servers_store.attach_to_scrim`** creates the server (committing inside `create_server`),
   *then* reserves the credit, and deletes the server if the reservation fails. Two
   transactions: a crash in between leaves a server that reserved nothing. FR-012 names this
   pair explicitly. Fix: one transaction — `create_server` must not commit when called as part
   of an attach, and the reservation commits both halves together.

2. **`accounts.upsert_on_login`** reads, then inserts or updates. Two simultaneous first
   sign-ins for the same account — two pods, or a double-clicked login — both see
   `existing is None` and both insert → unique violation surfacing as an error page. SQLite's
   serialized writer made this nearly unreachable; two app copies (FR-014) make it reachable.
   Fix: `INSERT … ON CONFLICT (steam_id) DO UPDATE`, matching how `rgl_store` already writes.

## R20 — One access path, enforced

FR-023 requires every process to reach the store through a single shared path. Two modules
currently bypass `app/db.py`:

- **`scripts/seed_demo_team.py:325`** — `sqlite3.connect(args.db)` directly, with its own
  `--db` path argument. Must go through the shared connection path; `--db` becomes a DSN
  override.
- **`tests/integration/test_auth.py:33,55`** — `sqlite3.connect(app.config["DB_PATH"])`.
  Must use the app's connection.

After this, `app/db.py` is the only module that opens a connection, and connection settings,
credentials, and integrity guarantees cannot drift between the web app and the CronJobs.

## R21 — Decommissioning the old store

FR-005 and SC-008 require the old store gone, not merely unused — a leftover file reachable
by a running process is a second, stale source of truth.

- `deploy/pvc.yaml` deleted; the `data` volume and its mount removed from `deployment.yaml`
  and **both** CronJob manifests.
- `DB_PATH` removed from `app/config.py`, `Dockerfile` (including the `/data` dir, the
  `VOLUME` declaration, and the chown), README, and every manifest.
- Local `app.db` deleted; `.gitignore`'s "SQLite user DB lives on a PVC" comment corrected.
- `deployment.yaml` goes `replicas: 1` → `2` with an explicit `RollingUpdate` strategy — the
  whole point of User Story 3, and impossible while a ReadWriteOnce PVC was attached.

The app container keeps `readOnlyRootFilesystem: true`; with no PVC it needs no writable path
at all.

---

## Resolved unknowns

| # | Question | Resolution |
|---|---|---|
| R1 | Driver | psycopg 3 sync, `dict_row` — preserves the existing call shape |
| R2 | Placeholders | Mechanical `?` → `%s`; no runtime shim |
| R3 | Insert ids | `RETURNING id` (11 sites) |
| R4 | Upserts | `ON CONFLICT` carries over; `INSERT OR *` rewritten (8 sites) |
| R5 | Timestamps | Stay `text` — protects FR-001/SC-007; conversion is a clean follow-up |
| R6 | Booleans | Stay integer (`smallint`) |
| R7 | Identity | `GENERATED BY DEFAULT AS IDENTITY`; sequence/explicit-id trap noted |
| R8 | Type strictness | Boundary coercion audit; one confirmed site (`routes/credits.py:42`) |
| R9 | **Credit-spend race** | **Per-account `SELECT … FOR UPDATE` before the conditional insert** |
| R10 | Exactly-once | `UNIQUE (method, provider_ref)` unchanged; audit post-error rollback paths |
| R11 | One server per scrim | Partial unique index carries over verbatim |
| R12 | Foreign keys | Always on; FR-011 strengthened for free |
| R13 | Migrations | Ordered `.sql` + tiny runner + advisory lock (FR-015, FR-019) |
| R14 | Pooling | `psycopg_pool`, per process, created after fork, `check_connection` |
| R15 | Topology | Single-instance StatefulSet + PVC + Service, in-repo |
| R16 | Backup/restore | `pg_dump -Fc` CronJob + `latest.json` marker; rehearsed `pg_restore` |
| R17 | Readiness | `/healthz` does `SELECT 1`; 503 + log on failure |
| R18 | Test isolation | One DB, migrate once, `TRUNCATE … RESTART IDENTITY CASCADE` per test |
| R19 | **Transaction gaps** | **`attach_to_scrim` and `upsert_on_login` fixed as part of this work** |
| R20 | Single access path | `seed_demo_team.py` and `test_auth.py` routed through `app/db.py` |
| R21 | Decommission | PVC, `DB_PATH`, and volume mounts removed; `replicas: 2` |

**No `[NEEDS CLARIFICATION]` markers remain.** The two spec-level ones (migrate vs empty,
one engine vs two) were resolved in the 2026-07-30 clarification session before planning.

## Sources

- psycopg 3 documentation — `Connection.execute`, `psycopg.rows.dict_row`, `psycopg_pool`
  connection checking, transaction and error semantics (`InFailedSqlTransaction`).
- PostgreSQL 17 documentation — `INSERT … ON CONFLICT`, partial unique indexes, identity
  columns, `SELECT … FOR UPDATE` row locking, transaction isolation (READ COMMITTED),
  advisory locks, `pg_dump`/`pg_restore`, `TRUNCATE … RESTART IDENTITY`.
- This repository — measured call-site counts (table above), `specs/005-servers-page/`
  research R6–R9 (the SQLite concurrency work this feature supersedes), constitution v4.0.0.
