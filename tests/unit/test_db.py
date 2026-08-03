"""The store access path: integrity, concurrency, the migration runner, and the pool.

**These tests used to assert SQLite pragmas** — WAL on, `busy_timeout` non-zero,
`foreign_keys` on. Those were never the point; they were the mechanism by which three
behaviors were true. Feature 006 keeps the behaviors and drops the mechanism, so the
assertions are behavioral now: an orphan reference is refused, a reader is not blocked by
an open write, and concurrent writers all succeed.

That is a strictly better test. `PRAGMA foreign_keys = 1` proved a setting was applied to
one connection; "this insert raises" proves the guarantee holds — and under Postgres it
holds on every connection with no pragma to remember and no way to switch it off.
"""
import threading

import psycopg
import pytest

from app import db


NOW = "2026-07-29T00:00:00+00:00"


def _conn():
    """A connection outside the request path, for tests that need two at once."""
    return psycopg.connect(db.dsn(), row_factory=psycopg.rows.dict_row)


def _make_user(conn, steam_id, name="Tester"):
    conn.execute(
        "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
        " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (steam_id, name, NOW, NOW),
    )


# --- integrity ---------------------------------------------------------------------

def test_an_orphan_reference_is_refused(app):
    """Was `PRAGMA foreign_keys == 1`. What actually mattered is this.

    Every REFERENCES clause written before feature 005 was decorative, because SQLite
    defaults foreign keys off and nobody had turned them on. Postgres enforces them
    always, on every connection (FR-011, research R12).
    """
    conn = _conn()
    try:
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO credit_ledger (steam_id, delta, kind, cause, created_at)"
                " VALUES ('76561190000000000', 5, 'grant', 'nobody', %s)", (NOW,)
            )
            conn.commit()
    finally:
        conn.close()


def test_payments_cannot_credit_the_same_trade_twice(app):
    """The exactly-once guarantee, enforced by the store rather than by the poller
    behaving well — it re-reads the same offers every run and can be run by hand."""
    conn = _conn()
    try:
        _make_user(conn, "76561198000000001", "Payer")
        insert = (
            "INSERT INTO payments (steam_id, method, provider_ref, state,"
            " items_expected, created_at, updated_at) VALUES"
            " ('76561198000000001', 'steam_trade', 'offer-1', 'complete', 2, %s, %s)"
        )
        conn.execute(insert, (NOW, NOW))
        conn.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, (NOW, NOW))
            conn.commit()
    finally:
        conn.close()


def test_a_scrim_can_have_only_one_server(app):
    conn = _conn()
    try:
        _make_user(conn, "76561198000000001", "Cap")
        conn.execute(
            "INSERT INTO rgl_teams (rgl_team_id, name, format, updated_at)"
            " VALUES (101, 'Alpha', 'sixes', %s)", (NOW,)
        )
        # Let the identity column generate the id rather than supplying one. An explicit
        # insert does not advance the sequence, so mixing the two styles in one table
        # collides on the next generated id (research R7). Nothing here needs a fixed id.
        scrim_id = conn.execute(
            "INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,"
            " status, created_by, created_at, updated_at) VALUES"
            " ('sixes', '2026-08-01T18:00:00+00:00', 'listing', 101, 'open',"
            " '76561198000000001', %s, %s) RETURNING id", (NOW, NOW)
        ).fetchone()["id"]
        insert = (
            "INSERT INTO servers (scrim_id, owner_steam_id, team_id, state, name, map,"
            " max_slots, created_at, updated_at) VALUES (%s, '76561198000000001', 101,"
            " 'scheduled', 'S', 'cp_process_final', 24, %s, %s)"
        )
        conn.execute(insert, (scrim_id, NOW, NOW))
        conn.commit()
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, (scrim_id, NOW, NOW))
            conn.commit()
    finally:
        conn.close()


# --- concurrency -------------------------------------------------------------------

def test_a_reader_is_not_blocked_by_an_open_write(app):
    """The scenario the poller creates: one process mid-write while another reads.

    Under SQLite's default journal mode the reader failed outright, which is why WAL was
    turned on. Postgres readers never block on writers at all — MVCC, not a mode.
    """
    writer, reader = _conn(), _conn()
    try:
        writer.execute(
            "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
            " VALUES ('76561198000000900', 'Writer', %s, %s)", (NOW, NOW)
        )
        # Deliberately not committed: the reader must proceed against the pre-write
        # snapshot rather than wait for or fail on the open transaction.
        assert reader.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0
        writer.commit()
        assert reader.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 1
    finally:
        writer.close()
        reader.close()


def test_concurrent_writers_all_succeed(app):
    """Was "writers wait instead of failing". Now they do not even wait.

    Two writers is what a CronJob overrunning into the next tick looks like. Under SQLite
    the busy timeout converted an instant `database is locked` into a bounded wait; here
    there is no global write lock to wait on, so unrelated rows never contend (FR-008).
    """
    errors = []

    def write(steam_id):
        try:
            with psycopg.connect(db.dsn()) as conn:
                conn.execute(
                    "INSERT INTO users (steam_id, persona_name, created_at,"
                    " last_login_at) VALUES (%s, 'Racer', %s, %s)", (steam_id, NOW, NOW)
                )
                conn.commit()
        except Exception as exc:  # noqa: BLE001 — any failure is the thing under test
            errors.append(f"{type(exc).__name__}: {exc}")

    threads = [threading.Thread(target=write, args=(f"7656119800000{i:04d}",))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"contended writes failed: {errors}"
    with _conn() as conn:
        assert conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 8


# --- the migration runner ----------------------------------------------------------

def test_migrate_is_idempotent(app):
    """Was `init_schema` idempotence via CREATE TABLE IF NOT EXISTS.

    Now it is a recorded version: a migration already in `schema_migrations` is not
    re-applied, which is what lets an app copy start against a store somebody else
    already migrated (FR-015, FR-019).
    """
    assert db.migrate() == [], "no migration should be pending after session setup"
    assert db.migrate() == []


def test_every_migration_file_is_recorded_exactly_once(app):
    versions = sorted(p.stem for p in db.MIGRATIONS_DIR.glob("*.sql"))
    assert versions, "expected at least 0001_initial.sql"

    with _conn() as conn:
        rows = conn.execute(
            "SELECT version, COUNT(*) AS c FROM schema_migrations"
            " GROUP BY version ORDER BY version"
        ).fetchall()

    assert [r["version"] for r in rows] == versions
    assert all(r["c"] == 1 for r in rows), "a version was recorded twice"


def test_migrations_apply_in_filename_order(app):
    """The ordering rule migrations/README.md documents, asserted rather than trusted."""
    with _conn() as conn:
        applied = [
            r["version"] for r in
            conn.execute("SELECT version FROM schema_migrations ORDER BY applied_at, version")
            .fetchall()
        ]
    assert applied == sorted(applied)


def test_the_schema_the_migration_creates(app):
    """Every entity the spec lists must exist — the store has to account for all of them."""
    with _conn() as conn:
        names = {
            r["tablename"] for r in
            conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            .fetchall()
        }
    assert {
        "users", "rgl_links", "rgl_teams", "rgl_memberships", "rgl_rosters",
        "rgl_roster_meta", "rgl_seasons", "rgl_season_teams", "scrims",
        "scrim_attendance", "steam_trade_links", "payments", "servers",
        "credit_ledger", "schema_migrations",
    } == names


def test_servers_has_no_administrative_password_column(app):
    """Constitution IV. The absence is load-bearing and would survive an engine change
    unexamined unless something checked it — and what is not in the store cannot appear
    in a backup of it either."""
    with _conn() as conn:
        columns = {
            r["column_name"] for r in
            conn.execute("SELECT column_name FROM information_schema.columns"
                         " WHERE table_name = 'servers'").fetchall()
        }
    assert not {c for c in columns if "rcon" in c or "admin" in c}
    assert "join_password" in columns, "the join password is not an administrative one"


# --- the pool and the connection surface -------------------------------------------

def test_rows_are_dicts(app):
    with app.test_request_context():
        row = db.get_db().execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1
    assert dict(row) == {"one": 1}


def test_one_connection_per_request_context(app):
    with app.test_request_context():
        assert db.get_db() is db.get_db()


def test_close_db_returns_the_connection_to_the_pool(app):
    with app.test_request_context():
        db.get_db()
        pool = db._get_pool()
        in_use = pool.get_stats()["requests_num"]
        db.close_db()
        assert "db" not in __import__("flask").g
    assert pool.get_stats()["requests_num"] >= in_use


def test_the_pool_is_not_created_at_import():
    """A pool built at import time would be inherited across Gunicorn's fork and share
    sockets between workers (research R14). It must be created lazily, per process."""
    import importlib

    module = importlib.import_module("app.db")
    source = (module.MIGRATIONS_DIR.parent / "app" / "db.py").read_text()
    assert "_pool: ConnectionPool | None = None" in source
    assert "def _get_pool" in source


def test_transaction_commits_on_success(app):
    with app.test_request_context():
        with db.transaction() as conn:
            _make_user(conn, "76561198000000010", "Committed")
        db.close_db()
    with _conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE steam_id = '76561198000000010'"
        ).fetchone()["c"] == 1


def test_transaction_rolls_back_on_failure(app):
    with app.test_request_context():
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                _make_user(conn, "76561198000000011", "Rolled back")
                raise RuntimeError("boom")
        db.close_db()
    with _conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE steam_id = '76561198000000011'"
        ).fetchone()["c"] == 0


def test_nested_transactions_commit_once_at_the_outermost_block(app):
    """`attach_to_scrim` opens a transaction and calls into `credits.reserve`, which wants
    one too. If the inner block committed, half an attach would land — the exact bug
    FR-012 exists to forbid."""
    with app.test_request_context():
        with pytest.raises(RuntimeError):
            with db.transaction() as conn:
                _make_user(conn, "76561198000000012", "Outer")
                with db.transaction():
                    pass  # inner block exits cleanly and must NOT commit
                raise RuntimeError("outer fails after the inner block returned")
        db.close_db()
    with _conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) AS c FROM users WHERE steam_id = '76561198000000012'"
        ).fetchone()["c"] == 0


# --- reachability ------------------------------------------------------------------

def test_check_succeeds_against_a_reachable_store(app):
    db.check()  # raises on failure


def test_the_dsn_is_redacted_to_host_port_database():
    """Constitution IV: credentials never reach a log or a client. An operator still needs
    to know *which* store was unreachable."""
    redacted = db.redact_dsn("postgresql://tf2app:hunter2@db.internal:5432/tf2hosting")
    assert redacted == "db.internal:5432/tf2hosting"
    assert "hunter2" not in redacted
    assert "tf2app" not in redacted


def test_redacting_an_unparseable_or_missing_dsn_never_raises():
    assert db.redact_dsn("this is not a dsn") in {"<unparseable DSN>", "localhost:5432/?"}
