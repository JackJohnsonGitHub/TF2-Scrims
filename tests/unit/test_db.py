"""Connection pragmas (T004/T005).

These are not cosmetic settings. Feature 005 introduces a payment poller that runs as
a separate process from Gunicorn's workers, so writes genuinely contend for the first
time. Without WAL and a busy timeout the contended write raises `database is locked`,
and on the payment path that presents as a trade that silently never got credited.
"""
import sqlite3
import threading

import pytest

from app.db import BUSY_TIMEOUT_MS, connect, init_schema


def test_wal_is_enabled(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_busy_timeout_is_not_zero(tmp_path):
    # SQLite's default is 0: a busy database fails instantly instead of waiting.
    conn = connect(str(tmp_path / "t.db"))
    try:
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
    finally:
        conn.close()


def test_foreign_keys_are_enforced(tmp_path, app):
    """Off by default in SQLite, which has quietly made every REFERENCES clause in
    SCHEMA decorative. The credit tables depend on referential integrity."""
    conn = connect(app.config["DB_PATH"])
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO credit_ledger (steam_id, delta, kind, cause, created_at)"
                " VALUES ('76561190000000000', 5, 'grant', 'nobody', '2026-07-29T00:00:00+00:00')"
            )
            conn.commit()
    finally:
        conn.close()


def test_a_reader_is_not_blocked_by_an_open_write(app):
    """The scenario the poller creates: one process mid-write while another reads.
    Under the default journal mode the reader fails outright."""
    writer = connect(app.config["DB_PATH"])
    reader = connect(app.config["DB_PATH"])
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute(
            "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
            " VALUES ('76561198000000900', 'Writer', '2026-07-29T00:00:00+00:00',"
            " '2026-07-29T00:00:00+00:00')"
        )
        # Must not raise: WAL keeps readers going against the pre-write snapshot.
        assert reader.execute("SELECT COUNT(*) FROM users").fetchone()[0] >= 0
        writer.commit()
    finally:
        writer.close()
        reader.close()


def test_concurrent_writers_wait_instead_of_failing(app):
    """Two writers is exactly what a CronJob overrunning into the next tick looks
    like. The busy timeout must convert an instant failure into a short wait."""
    errors = []

    def write(steam_id):
        conn = connect(app.config["DB_PATH"])
        try:
            conn.execute(
                "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
                " VALUES (?, 'Racer', '2026-07-29T00:00:00+00:00', '2026-07-29T00:00:00+00:00')",
                (steam_id,),
            )
            conn.commit()
        except sqlite3.OperationalError as exc:  # pragma: no cover - the failure we guard
            errors.append(str(exc))
        finally:
            conn.close()

    threads = [threading.Thread(target=write, args=(f"7656119800000{i:04d}",))
               for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"contended writes failed: {errors}"


def test_init_schema_is_idempotent(tmp_path):
    class Cfg:
        config = {"DB_PATH": str(tmp_path / "t.db")}

    init_schema(Cfg)
    init_schema(Cfg)  # every table is CREATE TABLE IF NOT EXISTS

    conn = connect(Cfg.config["DB_PATH"])
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()

    assert {"steam_trade_links", "payments", "credit_ledger", "servers"} <= names


def test_payments_cannot_credit_the_same_trade_twice(app):
    """The exactly-once guarantee, enforced by the store rather than by the poller
    behaving well — it re-reads the same offers every run and can be run by hand."""
    conn = connect(app.config["DB_PATH"])
    try:
        conn.execute(
            "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
            " VALUES ('76561198000000001', 'Payer', '2026-07-29T00:00:00+00:00',"
            " '2026-07-29T00:00:00+00:00')"
        )
        insert = (
            "INSERT INTO payments (steam_id, method, provider_ref, state,"
            " items_expected, created_at, updated_at) VALUES"
            " ('76561198000000001', 'steam_trade', 'offer-1', 'complete', 2,"
            " '2026-07-29T00:00:00+00:00', '2026-07-29T00:00:00+00:00')"
        )
        conn.execute(insert)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert)
            conn.commit()
    finally:
        conn.close()


def test_a_scrim_can_have_only_one_server(app):
    conn = connect(app.config["DB_PATH"])
    try:
        conn.executescript(
            "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
            " VALUES ('76561198000000001', 'Cap', '2026-07-29T00:00:00+00:00',"
            " '2026-07-29T00:00:00+00:00');"
            "INSERT INTO rgl_teams (rgl_team_id, name, format, updated_at)"
            " VALUES (101, 'Alpha', 'sixes', '2026-07-29T00:00:00+00:00');"
            "INSERT INTO scrims (id, format, scheduled_at, origin, proposer_team_id,"
            " status, created_by, created_at, updated_at) VALUES"
            " (1, 'sixes', '2026-08-01T18:00:00+00:00', 'listing', 101, 'open',"
            " '76561198000000001', '2026-07-29T00:00:00+00:00', '2026-07-29T00:00:00+00:00');"
        )
        insert = (
            "INSERT INTO servers (scrim_id, owner_steam_id, team_id, state, name, map,"
            " max_slots, created_at, updated_at) VALUES (1, '76561198000000001', 101,"
            " 'scheduled', 'S', 'cp_process_final', 24, '2026-07-29T00:00:00+00:00',"
            " '2026-07-29T00:00:00+00:00')"
        )
        conn.execute(insert)
        conn.commit()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(insert)
            conn.commit()
    finally:
        conn.close()
