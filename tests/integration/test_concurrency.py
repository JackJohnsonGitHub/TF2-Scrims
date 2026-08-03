"""The integrity rules, proven against the real engine (FR-026).

**This file is the reason feature 006 is not a find-and-replace.** Three guarantees the
platform relied on were held up by SQLite's single global writer, not by anything the
store enforced. Under a genuinely concurrent engine they stop holding for free, and the
spec is explicit that a violation must not be able to pass tests and fail in production —
so each one is exercised here against the same PostgreSQL the deployment uses.

Concurrency is threads holding **independent connections**, not threads sharing one. Each
connection is its own Postgres backend — a separate server-side process — so the database
sees exactly the contention two app pods or a pod and a CronJob would produce. The GIL is
irrelevant: every one of these tests is waiting on the server, not on Python.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest

from app import credits, payments, servers_store, steam_trade
from app import db as store
from app.credits import InsufficientCredits


NOW = "2026-07-29T00:00:00+00:00"
PAYER = "76561198000000501"
# The 32-bit account id inside PAYER's SteamID64. `save_trade_link` refuses a URL that
# belongs to somebody else, so these two have to agree.
PARTNER = 39734773
KEY_NAME = "Mann Co. Supply Crate Key"


@pytest.fixture
def concurrent_app(app):
    """An app whose pool can actually hold the workers this file starts.

    The default ceiling is 4 — right for a Gunicorn sync worker serving one request at a
    time, wrong for 20 threads in one process. The pool is per-process and built lazily,
    so closing it makes the next checkout rebuild it at this size.
    """
    app.config["DB_POOL_MAX"] = 24
    app.config["STEAM_API_KEY"] = "test-key"
    app.config["OPERATOR_TRADE_URL"] = (
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=operator")
    store.close_pool()
    yield app
    store.close_pool()


def _run(n, fn):
    """Fire `n` workers at the same instant and collect (result, exception) per worker.

    The barrier matters: without it the workers start staggered by thread-creation cost
    and the race the test exists to catch simply does not happen.
    """
    barrier = threading.Barrier(n)

    def worker(i):
        barrier.wait()
        try:
            return fn(i), None
        except Exception as exc:  # noqa: BLE001 — classifying failures is the point
            return None, exc

    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(worker, range(n)))


def _raw():
    return psycopg.connect(store.dsn(), row_factory=psycopg.rows.dict_row)


def _make_user(steam_id=PAYER, name="Payer"):
    with _raw() as conn:
        conn.execute(
            "INSERT INTO users (steam_id, persona_name, created_at, last_login_at)"
            " VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING", (steam_id, name, NOW, NOW))
        conn.commit()
    return steam_id


def _balance(steam_id=PAYER):
    with _raw() as conn:
        return conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS b FROM credit_ledger WHERE steam_id = %s",
            (steam_id,)).fetchone()["b"]


# --- FR-013: a balance cannot go negative (research R9) -----------------------------

def test_spend_race_cannot_drive_a_balance_negative(concurrent_app):
    """The finding that shapes this feature.

    An account holding exactly one credit, N processes each trying to reserve one. Under
    READ COMMITTED without the row lock, every one of them evaluates the balance check
    against a snapshot taken before any of the inserts, all of them see a sufficient
    balance, and all of them insert. **This test fails against a build without the
    `FOR UPDATE` in `credits._spend`** — that is the point of having it.
    """
    _make_user()
    with concurrent_app.test_request_context():
        credits.grant(PAYER, 1, "one credit, exactly")
        store.get_db().commit()
    assert _balance() == 1

    def reserve(i):
        with concurrent_app.app_context():
            return credits.reserve(PAYER, f"worker {i}", scrim_id=None, server_id=None)

    results = _run(8, reserve)
    winners = [r for r, exc in results if exc is None]
    refused = [exc for _, exc in results if isinstance(exc, InsufficientCredits)]
    other = [exc for _, exc in results if exc is not None
             and not isinstance(exc, InsufficientCredits)]

    assert other == [], f"unexpected failures: {other}"
    assert len(winners) == 1, f"{len(winners)} spends succeeded against a balance of 1"
    assert len(refused) == 7
    assert _balance() == 0
    assert _balance() >= 0, "the ledger went negative — paid compute, silently overdrawn"


def test_different_accounts_never_contend(concurrent_app):
    """The lock must be per-account, or it reintroduces the unrelated-writer contention
    FR-008 forbids: one team's captain buying time must not wait on another team's."""
    ids = [f"7656119800000{600 + i}" for i in range(8)]
    for steam_id in ids:
        _make_user(steam_id, f"User {steam_id[-3:]}")
        with concurrent_app.test_request_context():
            credits.grant(steam_id, 1, "one each")
            store.get_db().commit()

    def reserve(i):
        with concurrent_app.app_context():
            return credits.reserve(ids[i], "own credit")

    results = _run(8, reserve)
    assert [exc for _, exc in results if exc is not None] == []
    for steam_id in ids:
        assert _balance(steam_id) == 0


# --- FR-009 / SC-003: exactly-once crediting ----------------------------------------

def _offer(offer_id="7000000501", keys=2):
    items = (steam_trade.OfferItem(440, KEY_NAME, keys),)
    return steam_trade.TradeOffer(offer_id=offer_id, partner_accountid=PARTNER,
                                  state=steam_trade.STATE_ACCEPTED,
                                  items_to_receive=items)


def test_exactly_once_crediting_under_replay(concurrent_app, monkeypatch):
    """SC-003: the same completed payment replayed at least 10 times, including from
    processes running simultaneously, grants credits exactly once.

    Guaranteed by `UNIQUE (method, provider_ref)` in the store — not by the poller
    behaving well, which is the distinction that matters: it re-reads every offer on
    every run and can be run twice by hand.
    """
    monkeypatch.setattr(steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(0, 0))
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(0, 0))

    _make_user()
    with concurrent_app.test_request_context():
        payments.save_trade_link(
            PAYER, f"https://steamcommunity.com/tradeoffer/new/?partner={PARTNER}&token=abc")
        payments.start_payment(PAYER)
        store.get_db().commit()

    offer = _offer()

    def replay(_i):
        with concurrent_app.app_context():
            return payments.reconcile_offer(offer)

    results = _run(12, replay)
    unexpected = [exc for _, exc in results if exc is not None]
    assert unexpected == [], f"replay raised: {unexpected}"

    with _raw() as conn:
        dupes = conn.execute(
            "SELECT method, provider_ref, COUNT(*) AS c FROM payments"
            " GROUP BY 1, 2 HAVING COUNT(*) > 1").fetchall()
        grants = conn.execute(
            "SELECT COUNT(*) AS c FROM credit_ledger"
            " WHERE kind = 'grant' AND payment_id IS NOT NULL").fetchone()["c"]
        completed = conn.execute(
            "SELECT COUNT(*) AS c FROM payments WHERE state = 'complete'").fetchone()["c"]

    assert dupes == [], "the same trade was recorded as two payments"
    assert grants == 1, f"{grants} grants for one payment"
    assert completed == 1
    with concurrent_app.test_request_context():
        assert _balance() == payments.credits_for_keys(2)


# --- FR-010 / FR-011 / FR-012: one server per scrim, atomically ---------------------

def _scrim_and_team(steam_id):
    with _raw() as conn:
        conn.execute(
            "INSERT INTO rgl_teams (rgl_team_id, name, format, updated_at)"
            " VALUES (777, 'Alpha', 'sixes', %s) ON CONFLICT DO NOTHING", (NOW,))
        scrim_id = conn.execute(
            "INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id, status,"
            " created_by, created_at, updated_at)"
            " VALUES ('sixes', '2099-08-01T18:00:00+00:00', 'listing', 777, 'open',"
            " %s, %s, %s) RETURNING id", (steam_id, NOW, NOW)).fetchone()["id"]
        conn.commit()
    return scrim_id


def test_two_simultaneous_attaches_leave_exactly_one_server(concurrent_app):
    """FR-010 by the partial unique index, FR-012 by the single transaction.

    The loser must not be charged. Before this feature the server was committed first and
    the credit reserved second, so a failure between them left a server that had reserved
    nothing — and the compensating DELETE ran on a connection the failure had already
    poisoned (research R19).
    """
    _make_user()
    with concurrent_app.test_request_context():
        credits.grant(PAYER, 5, "plenty")
        store.get_db().commit()
    scrim_id = _scrim_and_team(PAYER)
    scrim = {"id": scrim_id, "scheduled_at": "2099-08-01T18:00:00+00:00",
             "proposer_team_id": 777, "opponent_team_id": None}

    def attach(_i):
        with concurrent_app.app_context():
            return servers_store.attach_to_scrim(PAYER, dict(scrim), team_id=777)

    results = _run(4, attach)
    winners = [r for r, exc in results if exc is None]

    with _raw() as conn:
        servers = conn.execute(
            "SELECT COUNT(*) AS c FROM servers WHERE scrim_id = %s", (scrim_id,)
        ).fetchone()["c"]
        reserved = conn.execute(
            "SELECT COUNT(*) AS c FROM credit_ledger WHERE kind = 'reserve'"
            " AND scrim_id = %s", (scrim_id,)).fetchone()["c"]

    assert servers == 1, f"{servers} servers attached to one scrim"
    assert len(winners) == 1
    # One credit consumed, not four: the losers' reservations rolled back with their
    # servers rather than being charged for compute nobody got.
    assert reserved == 1
    assert _balance() == 4


def test_an_orphan_reference_is_refused_under_concurrency(concurrent_app):
    """FR-011. Enforced on every connection, with no pragma to remember."""
    def orphan(i):
        with _raw() as conn:
            conn.execute(
                "INSERT INTO credit_ledger (steam_id, delta, kind, cause, created_at)"
                " VALUES (%s, 5, 'grant', 'nobody', %s)", (f"7656119999999{i:04d}", NOW))
            conn.commit()

    results = _run(4, orphan)
    assert all(isinstance(exc, psycopg.errors.ForeignKeyViolation)
               for _, exc in results), [exc for _, exc in results]


# --- FR-015: several copies initialise at once --------------------------------------

def test_concurrent_migrations_initialise_exactly_once(concurrent_app):
    """US3 acceptance 3: several app copies starting at once against one store.

    The advisory lock serializes them — the first takes it, the rest block briefly and
    then find every migration already applied. Nobody fails because it lost the race, and
    nobody applies a migration twice. A naked `CREATE TABLE IF NOT EXISTS` from two
    connections at once can genuinely collide on Postgres system catalogs, so the lock is
    doing real work rather than decorating the startup path.
    """
    expected = sorted(p.stem for p in store.MIGRATIONS_DIR.glob("*.sql"))

    def migrate(_i):
        with concurrent_app.app_context():
            return store.migrate()

    results = _run(6, migrate)
    failures = [exc for _, exc in results if exc is not None]
    assert failures == [], f"a copy failed to start because it lost the race: {failures}"

    # Every migration was already applied by the session fixture, so each racer correctly
    # finds nothing to do. What matters is that none of them errored and none double-applied.
    assert all(applied == [] for applied, _ in results)

    with _raw() as conn:
        rows = conn.execute(
            "SELECT version, COUNT(*) AS c FROM schema_migrations GROUP BY version"
        ).fetchall()
    assert sorted(r["version"] for r in rows) == expected
    assert all(r["c"] == 1 for r in rows), "a migration was recorded twice"


def test_a_migration_applies_exactly_once_from_an_empty_store(concurrent_app):
    """The same race, but from genuinely nothing — the state a first deploy is in.

    Runs in its own schema so it can drop and rebuild without disturbing the suite's.
    """
    with _raw() as conn:
        conn.execute("DROP SCHEMA IF EXISTS racetest CASCADE")
        conn.execute("CREATE SCHEMA racetest")
        conn.commit()

    dsn = store.dsn() + "?options=-csearch_path%3Dracetest"

    def migrate(_i):
        with concurrent_app.app_context():
            concurrent_app.config["DATABASE_URL"] = dsn
            return store.migrate()

    try:
        results = _run(6, migrate)
        failures = [exc for _, exc in results if exc is not None]
        assert failures == [], f"racing copies failed: {failures}"

        # Exactly one racer did the work; the other five found it already done.
        did_work = [applied for applied, _ in results if applied]
        assert len(did_work) == 1, f"{len(did_work)} copies applied migrations"

        with psycopg.connect(dsn, row_factory=psycopg.rows.dict_row) as conn:
            rows = conn.execute(
                "SELECT version, COUNT(*) AS c FROM schema_migrations GROUP BY version"
            ).fetchall()
        assert sorted(r["version"] for r in rows) == did_work[0]
        assert all(r["c"] == 1 for r in rows)
    finally:
        concurrent_app.config["DATABASE_URL"] = store.Config.DATABASE_URL
        with _raw() as conn:
            conn.execute("DROP SCHEMA IF EXISTS racetest CASCADE")
            conn.commit()


# --- FR-008 / SC-002: sustained contention ------------------------------------------

def test_sustained_contention_produces_no_failures(concurrent_app):
    """SC-002: at least 20 simultaneous users plus the payment poller and the reconciler
    writing — zero failures from store contention.

    This is the 8pm-Sunday scenario, and the whole reason the store was the constraint:
    against SQLite every one of these paths could return `database is locked`, and the
    one that failed might be the one crediting somebody's payment.
    """
    _make_user()
    with concurrent_app.test_request_context():
        credits.grant(PAYER, 40, "budget for the evening")
        store.get_db().commit()
    scrim_id = _scrim_and_team(PAYER)

    def mixed(i):
        with concurrent_app.app_context():
            if i % 10 == 0:
                # A writer on the credit path — what the poller does.
                credits.grant(PAYER, 1, f"poller {i}")
                store.get_db().commit()
            elif i % 10 == 1:
                # A writer on the server path — what the reconciler does.
                servers_store.create_server(
                    owner_steam_id=PAYER, team_id=777, name=f"srv {i}",
                    map_name="cp_process_final", max_slots=24, state="stopped")
            else:
                # Readers: the pages eighteen players are loading.
                credits.available_credits(PAYER)
                credits.ledger(PAYER)
                servers_store.accessible_servers(PAYER, [777])
                store.get_db().execute(
                    "SELECT COUNT(*) AS c FROM scrims WHERE id = %s", (scrim_id,)
                ).fetchone()
            return "ok"

    results = _run(24, mixed)
    failures = [exc for _, exc in results if exc is not None]
    assert failures == [], f"{len(failures)} of 24 concurrent operations failed: {failures}"
    assert _balance() >= 0
