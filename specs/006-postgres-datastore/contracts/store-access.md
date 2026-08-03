# Contract: The store access path

**Feature**: `006-postgres-datastore` · Follows the convention of
[`005/contracts/steam-trade-client.md`](../../005-servers-page/contracts/steam-trade-client.md).

`app/db.py` is **the only module in the repository permitted to open a connection to the
store** (FR-023). The web app, the payment poller, the server reconciler, the seed script,
and the test suite all reach Postgres through this surface — which is what stops connection
settings, credentials, and integrity guarantees from drifting between the request path and
the background jobs.

Two modules bypass it today and must be brought in: `scripts/seed_demo_team.py` and
`tests/integration/test_auth.py` (research R20).

---

## Configuration

| Variable | Meaning | Source |
|---|---|---|
| `DATABASE_URL` | libpq connection string (`postgresql://user:pass@host:5432/db`) | **OpenBao** → k8s Secret (FR-020) |
| `DB_POOL_MIN` | Pool floor per process. Default `1` | env, optional |
| `DB_POOL_MAX` | Pool ceiling per process. Default `4` | env, optional |
| `DB_CONNECT_TIMEOUT` | Seconds to wait for a connection. Default `5` | env, optional |

`DB_PATH` **is removed** — from `config.py`, the `Dockerfile`, every manifest, and the README
(FR-005, research R21).

**`DATABASE_URL` contains a password and is therefore a secret** under constitution IV. It
MUST NOT be committed, logged, echoed by the seed script, included in an error message
returned to a client, or rendered into a template. `Config.validate()` extends to require it
in production, alongside `APP_SECRET_KEY`, `STEAM_API_KEY`, and `OPERATOR_TRADE_URL` — the
same fail-fast treatment, for the same reason: a store the app cannot reach must be a startup
failure, not a silence.

Where a connection failure must be reported (logs, the readiness endpoint), the DSN is
**redacted to `host:port/dbname`**. Never the credentials.

---

## Public surface

### `get_db() -> psycopg.Connection`

Per-request (or per-CLI-invocation) connection, checked out of this process's pool and
cached on Flask's `g`. Identical in shape to today's function — call sites do not change.

- `row_factory=dict_row`: rows are `dict`. `row["steam_id"]`, `dict(row)`, and `{**dict(r)}`
  all keep working. **Positional access (`row[0]`) does not** — the 8 existing sites are
  rewritten to named columns (`SELECT COUNT(*) AS c … ["c"]`).
- `autocommit=False`. A transaction opens implicitly on first execute and ends at
  `commit()` / `rollback()` — the same semantics `sqlite3` gave, so existing `db.commit()`
  calls stay where they are.

### `close_db(exc=None) -> None`

Registered on `teardown_appcontext`, unchanged. Returns the connection to the pool.
`putconn` rolls back any open transaction first, so uncommitted work is discarded when a
request ends — matching today's behavior on connection close.

### `transaction()` — context manager

```python
with transaction() as db:
    ...            # commits on clean exit, rolls back on any exception
```

For the multi-statement writes FR-012 requires to land atomically. Two callers at
introduction (research R19): `credits._spend` and `servers_store.attach_to_scrim`.

### `migrate() -> list[str]`

Applies pending migrations, returns the versions applied. Called once from `create_app()`,
replacing `init_schema()`. Protocol:

1. `SELECT pg_advisory_lock(<constant>)` — a fixed 64-bit key, one per deployment.
2. `CREATE TABLE IF NOT EXISTS schema_migrations (…)`.
3. Read applied versions; for each `migrations/*.sql` not yet applied, **in filename order**,
   apply it and insert its version **in one transaction**.
4. `pg_advisory_unlock(<constant>)`, in a `finally`.

**FR-015** — several app copies starting at once: the first takes the lock, the rest block
briefly and then find nothing to do. Exactly one initialisation takes effect; no copy fails
because it lost the race. Postgres DDL is transactional, so a migration that fails midway
leaves nothing half-created and the version is not recorded.

### `check() -> None`

`SELECT 1` against the store, with `DB_CONNECT_TIMEOUT`. Raises on failure. Used by
`/healthz` (FR-016) and by the test-session preflight (FR-024).

---

## Query conventions

Binding on every call site.

| Rule | Then | Now |
|---|---|---|
| Placeholders | `?` | `%s` |
| Row identity after insert | `cur.lastrowid` | `… RETURNING id` → `.fetchone()["id"]` |
| Insert-if-absent | `INSERT OR IGNORE` | `INSERT … ON CONFLICT DO NOTHING` |
| Insert-or-replace | `INSERT OR REPLACE` | `INSERT … ON CONFLICT (…) DO UPDATE` |
| Upsert | `ON CONFLICT … excluded.*` | **unchanged** |
| Null coalesce | `IFNULL(x, y)` | `COALESCE(x, y)` |
| Case-insensitive sort | `ORDER BY name COLLATE NOCASE` | `ORDER BY lower(name)` |
| Row type annotations | `sqlite3.Row` | `dict` |
| Aggregate column access | `.fetchone()[0]` | `SELECT … AS c` → `.fetchone()["c"]` |

**Parameter types are now strict.** SQLite silently coerced `'5'` into an `integer` column;
Postgres raises. Route handlers must coerce at the boundary. One confirmed site today —
`app/routes/credits.py:42` passes `request.form.get("scrim_id")` (a `str`) into a column
typed `integer` (research R8).

---

## Transaction rules

Three rules, each carrying a requirement.

**1. A failed statement poisons the transaction.** Postgres raises
`InFailedSqlTransaction` on every subsequent statement until a rollback; SQLite let you carry
on. Any `except` block that touches the connection MUST roll back first.

Already correct: `payments._complete`, `payments._claim_offer`, `credits._spend`. The sweep
for other paths is a task.

**2. Spending credits takes a per-account row lock.** The invariant is FR-013 (a balance can
never go negative) and the race is research R9. Inside one transaction:

```sql
SELECT 1 FROM users WHERE steam_id = %s FOR UPDATE;   -- serialize this account
INSERT INTO credit_ledger (…)
SELECT %s, %s, …
WHERE (SELECT COALESCE(SUM(delta), 0) FROM credit_ledger WHERE steam_id = %s) >= %s;
-- rowcount == 1 → spent; rowcount == 0 → InsufficientCredits
COMMIT;
```

Applies to `reserve` and `spend_extension` (every path through `_spend`). It does **not**
apply to `grant` or `release`: both are additive and cannot violate the invariant.

- Two spends by **different accounts** never contend — different rows, different locks
  (FR-008).
- The locked region contains **no network I/O**. `spend_extension` is the mid-match path that
  feature 005's SC-010 requires to complete in seconds, and it stays a pure local write.

**3. A credit movement and the thing it pays for commit together** (FR-012).

- *Grant + payment completion* — already one transaction (`payments._complete`). Unchanged.
- *Reservation + server creation* — **currently two** (`servers_store.attach_to_scrim` commits
  the server, then reserves, then deletes on failure). Becomes one `transaction()` block:
  `create_server` must not commit when called as part of an attach.

---

## Error taxonomy

`psycopg.errors` replaces `sqlite3` exceptions. Call sites that catch by type change with it.

| Situation | Exception | Handling |
|---|---|---|
| Duplicate `(method, provider_ref)` | `UniqueViolation` | Already the exactly-once path (FR-009) |
| Second server for a scrim | `UniqueViolation` | FR-010 refusal |
| Orphan reference | `ForeignKeyViolation` | FR-011; a bug, not a user error — 500 and log |
| Wrong parameter type | `DatatypeMismatch` | Missing boundary coercion (R8) — a bug |
| Statement after a failed one | `InFailedSqlTransaction` | Missing rollback — a bug |
| Store unreachable | `OperationalError` | Readiness 503 + log (FR-016) |

`UniqueViolation` and `ForeignKeyViolation` both subclass `psycopg.IntegrityError`, so the
existing `pytest.raises(sqlite3.IntegrityError)` assertions translate directly.

**No database error text reaches a client.** Postgres messages name tables, columns, and
constraints; that is operator information, not user information.

---

## Connection lifecycle

One `psycopg_pool.ConnectionPool` per **process**, created lazily on first use.

- **After fork, never at import.** A pool built at import time would be inherited by every
  Gunicorn worker, sharing sockets between processes. Lazy creation gives each worker its own.
- `check=ConnectionPool.check_connection` — a connection broken while idle (the spec's "brief
  connection interruption" edge case) is discarded and replaced at checkout rather than handed
  to a request. No operator restart, no retry logic at call sites.
- Budget: 2 pods × 2 Gunicorn workers × `DB_POOL_MAX=4`, plus CronJob peaks ≈ 20 connections
  against Postgres's default `max_connections = 100`.
- CronJob invocations are short-lived processes: pool opens, work runs, process exits.

---

## Readiness (FR-016)

`GET /healthz` gains a store round trip.

| Condition | Response |
|---|---|
| `APP_READY=0` | `503 "not ready"` — unchanged drain override |
| `check()` raises | `503`, and the failure is **logged** with the redacted DSN |
| Otherwise | `200 "ok"` |

This is deliberately store-dependent: a pod that cannot reach the store must not receive
traffic, because the alternative is pages that render normally and show nothing.

Startup is the other half — `migrate()` cannot acquire a connection, so the pod crashes and
Kubernetes restarts it. Loud, which is the requirement.

---

## Test harness contract (FR-024, FR-026, FR-027)

**One engine everywhere** (FR-025). The suite runs against a real Postgres; there is no
in-memory substitute and no second dialect.

| Concern | Contract |
|---|---|
| Where | `DATABASE_URL`, defaulting to a local dev database |
| Preflight | A session-start hook calls `check()` **once**. On failure the run stops with an actionable message naming the `docker run` line and the variable to set — not 226 connection stack traces (FR-024 is explicit about this) |
| Schema | `migrate()` once per session |
| Isolation | `TRUNCATE <every table> RESTART IDENTITY CASCADE` between tests (FR-027) |
| Fixtures | The `app` fixture stops building a `tmp_path` DSN; `demo_servers`, `login`, and `link_team` keep their signatures |

`RESTART IDENTITY` matters: it resets sequences, so tests asserting on specific ids behave as
they do with a fresh file today.

**FR-026 requires the integrity rules be proven against this engine**, not assumed. At
minimum: concurrent spends against a balance of 1 (R9), the same payment replayed from
parallel processes (FR-009), two simultaneous attaches to one scrim (FR-010), an orphan
reference refused (FR-011), and concurrent `migrate()` calls (FR-015).
