"""PostgreSQL connection, transactions, and schema migration for the metadata store.

**This module is the only place in the repository permitted to open a connection to the
store** (FR-023). The web app, the payment poller, the server reconciler, the seed script,
and the test suite all reach Postgres through here — which is what stops connection
settings, credentials, and integrity guarantees from drifting between the request path and
the background jobs.

Feature 006 replaced SQLite. The shape of `get_db()` / `close_db()` is deliberately
unchanged, because psycopg 3's `Connection.execute()` returns a cursor exactly as
`sqlite3`'s did — so 167 call sites moved by rewriting placeholders, not by restructuring
(research R1). What is genuinely new is below `get_db()`: a pool, a transaction context
manager, and an advisory-locked migration runner.
"""
from __future__ import annotations

import logging
import os
import pathlib
from contextlib import contextmanager
from typing import Iterator

import psycopg
from flask import current_app, g, has_app_context
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import Config

log = logging.getLogger(__name__)

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent.parent / "migrations"

# A fixed 64-bit key, one per deployment: 0x74663206 = "tf2" + feature 006. Every app copy
# takes this same lock before migrating, which is what makes several copies starting at
# once safe (FR-015). The value is arbitrary but must never change — a new value would let
# an old and a new pod migrate concurrently.
MIGRATION_LOCK_KEY = 0x74663206

# One pool per process, created lazily on first use. Never at import: a pool built at
# import time would be inherited across Gunicorn's fork and share sockets between workers
# (research R14). `migrate()` and `check()` deliberately do not use it, so importing the
# app never creates one.
_pool: ConnectionPool | None = None


# --- configuration -----------------------------------------------------------------

def _setting(name: str, default: str) -> str:
    """Read config from the Flask app when there is one, else the environment, else `Config`.

    The seed script and the pytest preflight run outside an app context and still need to
    reach the same store by the same path. Falling through to `Config` last means all three
    resolve `DATABASE_URL` identically — a developer who forgot to export it gets the same
    local default the app would have used, rather than a confusing "not set" from one entry
    point and a working connection from another.
    """
    if has_app_context():
        value = current_app.config.get(name)
        if value not in (None, ""):
            return str(value)
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    return str(getattr(Config, name, default) or default)


def dsn() -> str:
    """The libpq connection string. Contains a password — never log or render it."""
    value = _setting("DATABASE_URL", "")
    if not value:
        raise RuntimeError(
            "DATABASE_URL is not set. Start a local store and export it:\n"
            "  docker run -d --name tf2-pg -p 5432:5432 -e POSTGRES_PASSWORD=dev "
            "-e POSTGRES_USER=tf2app -e POSTGRES_DB=tf2hosting postgres:17-alpine\n"
            '  export DATABASE_URL="postgresql://tf2app:dev@localhost:5432/tf2hosting"'
        )
    return value


def _connect_timeout() -> int:
    return int(float(_setting("DB_CONNECT_TIMEOUT", "5")))


def redact_dsn(value: str | None = None) -> str:
    """`host:port/dbname` — the only form of the DSN allowed into a log or a response.

    Constitution IV: store credentials must never be logged or sent to a client. An
    operator debugging a connection failure needs to know *which* store was unreachable,
    which is the host, port, and database name — never the password.
    """
    try:
        value = dsn() if value is None else value
    except RuntimeError:
        return "<DATABASE_URL unset>"
    try:
        info = conninfo_to_dict(value)
    except Exception:
        return "<unparseable DSN>"
    host = info.get("host") or "localhost"
    port = info.get("port") or "5432"
    dbname = info.get("dbname") or "?"
    return f"{host}:{port}/{dbname}"


# --- connections -------------------------------------------------------------------

def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        min_size = int(_setting("DB_POOL_MIN", "1"))
        max_size = int(_setting("DB_POOL_MAX", "4"))
        timeout = _connect_timeout()
        _pool = ConnectionPool(
            conninfo=dsn(),
            min_size=min_size,
            max_size=max_size,
            # Give up waiting for a free connection rather than hanging a request
            # indefinitely; an unreachable store must surface as a failure, not a stall.
            timeout=timeout,
            kwargs={
                "row_factory": dict_row,
                "autocommit": False,
                "connect_timeout": timeout,
            },
            # A connection broken while idle in the pool (the spec's "brief connection
            # interruption" edge case) is discarded and replaced at checkout rather than
            # handed to a request. No operator restart, no retry logic at the call sites.
            check=ConnectionPool.check_connection,
            name="tf2-hosting",
            open=False,
        )
        _pool.open()
    return _pool


def get_db() -> psycopg.Connection:
    """Per-request connection, checked out of this process's pool and cached on `g`.

    Rows are `dict` (`row_factory=dict_row`), so `row["steam_id"]`, `dict(row)`, and
    `{**dict(r)}` all work as they did with the old row factory. Positional access (`row[0]`)
    does not, which is why the few sites that used it now select named columns.

    `autocommit=False`: a transaction opens implicitly on first execute and ends at
    `commit()` / `rollback()` — the same semantics `sqlite3` gave, so existing
    `db.commit()` calls stay exactly where they are.
    """
    if "db" not in g:
        g.db = _get_pool().getconn()
    return g.db


def close_db(_exc=None) -> None:
    """Return the connection to the pool. Registered on `teardown_appcontext`.

    `putconn` rolls back any open transaction first, so uncommitted work is discarded when
    a request ends — matching what closing a SQLite connection did.
    """
    conn = g.pop("db", None)
    g.pop("_tx_depth", None)
    if conn is not None and _pool is not None:
        _pool.putconn(conn)


def close_pool() -> None:
    """Close this process's pool. For test teardown and orderly shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Commit on clean exit, roll back on any exception.

    For the multi-statement writes FR-012 requires to land atomically: a credit
    reservation and the server it reserves for, a credit grant and the payment state
    change that justifies it.

    **Nesting participates rather than nests.** `attach_to_scrim` opens a transaction and
    calls into `credits.reserve`, which wants one too. Only the outermost block commits;
    inner blocks are a no-op on exit. Without this the inner block would commit half an
    attach, which is the exact bug FR-012 exists to forbid.
    """
    db = get_db()
    depth = g.get("_tx_depth", 0)
    g._tx_depth = depth + 1
    try:
        yield db
    except BaseException:
        if depth == 0:
            db.rollback()
        g._tx_depth = depth
        raise
    else:
        if depth == 0:
            db.commit()
        g._tx_depth = depth


def check() -> None:
    """`SELECT 1` against the store. Raises on failure.

    Used by `/healthz` (FR-016) and by the pytest session preflight (FR-024). Deliberately
    a fresh connection rather than a pooled one: this answers "is the store reachable right
    now", and it has to work before any pool exists.
    """
    with psycopg.connect(dsn(), connect_timeout=_connect_timeout()) as conn:
        conn.execute("SELECT 1")


# --- migrations --------------------------------------------------------------------

def migrate() -> list[str]:
    """Apply pending migrations in filename order. Returns the versions applied.

    Called once from `create_app()`, replacing the old `init_schema()`. Protocol
    (FR-015, FR-019):

    1. Take `pg_advisory_lock(MIGRATION_LOCK_KEY)`.
    2. Ensure `schema_migrations` exists.
    3. Apply each `migrations/*.sql` not yet recorded, in filename order, each inside its
       own transaction together with the row recording it.
    4. Release the lock in a `finally`.

    Several app copies starting at once: the first takes the lock, the rest block briefly
    and then find nothing to do. Exactly one initialisation takes effect and no copy fails
    because it lost the race. A naked `CREATE TABLE IF NOT EXISTS` from two connections at
    once can genuinely collide on Postgres system catalogs, so the lock is doing real work.

    Postgres DDL is transactional, so a migration that fails midway leaves nothing
    half-created and its version is not recorded.

    Uses its own connection, not the pool — this runs at startup, potentially before fork,
    and it needs a session-level lock held across several transactions.
    """
    applied: list[str] = []
    with psycopg.connect(
        dsn(), autocommit=True, row_factory=dict_row, connect_timeout=_connect_timeout()
    ) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "    version     text PRIMARY KEY,"
                "    applied_at  timestamptz NOT NULL DEFAULT now()"
                ")"
            )
            done = {
                row["version"]
                for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
            }
            for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
                version = path.stem
                if version in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text())
                    conn.execute(
                        "INSERT INTO schema_migrations (version) VALUES (%s)", (version,)
                    )
                applied.append(version)
                log.info("applied migration %s", version)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK_KEY,))
    return applied
