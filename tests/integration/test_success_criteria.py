"""Success criteria that can be asserted structurally (U1 from /speckit-analyze).

Most of the spec's success criteria are latency or interaction-count promises. Wall-clock
timing is not worth asserting in a test suite — it measures the CI runner, not the design.
What *is* worth pinning is the structural property each promise rests on:

- SC-010's "under 15 seconds mid-match" holds because extending does **no network I/O**.
  That is an invariant, and it would degrade silently the day someone adds a Steam lookup
  to that route — so it gets a test.
- SC-002's "no more than three interactions" and SC-001's "without navigating elsewhere"
  are really claims about *where the actions live*. Also testable.

SC-008 (a first-time visitor can describe the pricing model) is left to a human — it is a
comprehension claim, not a code property.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import credits, payments, steam_trade
from app import servers_store as store
from tests.conftest import rgl_team

PAYER = "76561197972611406"
TEAM_A, TEAM_B = 101, 202


@pytest.fixture
def captain(app, client, login, link_team):
    steam_id = login(PAYER, "Captain")
    link_team(steam_id, [rgl_team(TEAM_A, "Alpha", "ALP", "sixes")])
    app.config["STEAM_API_KEY"] = "test-key"
    app.config["OPERATOR_TRADE_URL"] = (
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=operator")
    return steam_id


def give_credits(app, steam_id, amount):
    with app.test_request_context():
        from app.db import get_db
        credits.grant(steam_id, amount, "test grant")
        get_db().commit()


def a_scrim(app, steam_id, days=2, status="confirmed"):
    from app.db import get_db
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        db = get_db()
        db.execute(
            "INSERT INTO rgl_teams (rgl_team_id, name, format, updated_at)"
            " VALUES (%s, 'Bravo', 'sixes', %s) ON CONFLICT DO NOTHING", (TEAM_B, now.isoformat(timespec="seconds")))
        cur = db.execute(
            """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                   opponent_team_id, status, created_by,
                                   created_at, updated_at)
               VALUES ('sixes', %s, 'proposal', %s, %s, %s, %s, %s, %s)
               RETURNING id""",
            ((now + timedelta(days=days)).isoformat(timespec="seconds"), TEAM_A, TEAM_B,
             status, steam_id, now.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")))
        scrim_id = cur.fetchone()["id"]
        db.commit()
        return scrim_id


def a_running_server(app, steam_id, minutes_left=10):
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        return store.create_server(
            owner_steam_id=steam_id, team_id=TEAM_A, name="Match server",
            map_name="cp_process_final", max_slots=24, state=store.RUNNING,
            address="10.0.0.9:27015", players=12,
            window_starts_at=(now - timedelta(minutes=50)).isoformat(timespec="seconds"),
            window_ends_at=(now + timedelta(minutes=minutes_left)).isoformat(timespec="seconds"),
        )


def no_steam_allowed(monkeypatch):
    """Make any Steam call a hard failure."""
    def boom(*a, **k):
        raise AssertionError("this path must not touch Steam")
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration", boom)
    monkeypatch.setattr(payments.steam_trade, "get_received_offers", boom)
    monkeypatch.setattr(steam_trade, "get_trade_hold_duration", boom)
    monkeypatch.setattr(steam_trade, "get_received_offers", boom)
    monkeypatch.setattr(steam_trade.requests, "get", boom)


# --- SC-010: extending is fast because it does no network I/O -----------------------

def test_extending_makes_no_steam_call(client, app, captain, monkeypatch):
    """The invariant behind "under 15 seconds mid-match". Twelve people are waiting; this
    path must be a local ledger write and a timestamp bump, nothing else. It would degrade
    silently the day someone adds a Steam lookup here, so it is pinned."""
    give_credits(app, captain, 3)
    server_id = a_running_server(app, captain)
    no_steam_allowed(monkeypatch)

    resp = client.post(f"/servers/{server_id}/extend", follow_redirects=True)

    assert resp.status_code == 200
    with app.test_request_context():
        assert credits.available_credits(captain) == 2
        assert store.minutes_remaining(store.get_server(server_id)) >= 39


def test_viewing_a_server_makes_no_steam_call(client, app, captain, monkeypatch):
    """Same reasoning for the read path: a Steam outage must not slow down or break the
    page a team opens five minutes before a match."""
    give_credits(app, captain, 1)
    server_id = a_running_server(app, captain)
    no_steam_allowed(monkeypatch)

    assert client.get("/servers").status_code == 200
    assert client.get(f"/servers/{server_id}").status_code == 200


def test_extend_is_reachable_from_both_pages_a_team_would_already_be_on(
        client, app, captain):
    """SC-010's "without leaving the page you are on". Mid-match a captain is looking at
    either the server or the scrim — the action has to be on both."""
    give_credits(app, captain, 2)
    scrim_id = a_scrim(app, captain)
    with app.test_request_context():
        store.attach_to_scrim(captain, dict(
            id=scrim_id, scheduled_at=(datetime.now(timezone.utc)
                                       + timedelta(days=2)).isoformat(timespec="seconds"),
            proposer_team_id=TEAM_A, opponent_team_id=TEAM_B, proposer_name="Alpha"))
        server = store.server_for_scrim(scrim_id)
        store.set_state(server["id"], store.RUNNING)

    for path in (f"/servers/{server['id']}", f"/scrims/{scrim_id}"):
        body = client.get(path).get_data(as_text=True)
        assert f'action="/servers/{server["id"]}/extend"' in body, f"no extend on {path}"


# --- SC-002: a server request is a short path -------------------------------------

def test_a_server_request_is_at_most_three_interactions_from_the_servers_page(
        client, app, captain, monkeypatch):
    """SC-002. Asserted as path length rather than seconds: open /servers (1), follow the
    credits link (2), submit (3)."""
    from app.payments import save_trade_link
    with app.test_request_context():
        save_trade_link(captain, "https://steamcommunity.com/tradeoffer/new/"
                                 "?partner=12345678&token=abc123")
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(0, 0))

    # 1: the page names where to go.
    step1 = client.get("/servers").get_data(as_text=True)
    assert 'href="/credits"' in step1

    # 2: that page carries the action.
    step2 = client.get("/credits").get_data(as_text=True)
    assert 'action="/credits/trade/start"' in step2

    # 3: submitting it starts the payment.
    assert client.post("/credits/trade/start").status_code == 302
    with app.test_request_context():
        assert payments.open_payment(captain) is not None


def test_attaching_a_server_to_a_scrim_is_one_interaction_from_the_scrim(
        client, app, captain):
    give_credits(app, captain, 1)
    scrim_id = a_scrim(app, captain)

    body = client.get(f"/scrims/{scrim_id}").get_data(as_text=True)
    assert f'action="/scrims/{scrim_id}/server/attach"' in body

    client.post(f"/scrims/{scrim_id}/server/attach")
    with app.test_request_context():
        assert store.server_for_scrim(scrim_id) is not None


# --- SC-001: which of my scrims still need a server, without navigating away --------

def test_the_servers_page_names_upcoming_scrims_with_no_server(client, app, captain):
    """SC-001 / FR-016. The question this page has to answer at a glance is "which of my
    matches still have nowhere to play" — answerable here, not by touring /scrims."""
    give_credits(app, captain, 2)
    scrim_id = a_scrim(app, captain)

    body = client.get("/servers").get_data(as_text=True)
    assert "Scrims with no server" in body
    assert "Alpha" in body and "Bravo" in body
    assert f'action="/scrims/{scrim_id}/server/attach"' in body


def test_a_scrim_that_already_has_a_server_is_not_listed_as_needing_one(
        client, app, captain):
    give_credits(app, captain, 2)
    scrim_id = a_scrim(app, captain)
    client.post(f"/scrims/{scrim_id}/server/attach")

    body = client.get("/servers").get_data(as_text=True)
    assert "Scrims with no server" not in body


def test_a_past_scrim_is_not_listed_as_needing_a_server(client, app, captain):
    from app.db import get_db
    give_credits(app, captain, 2)
    scrim_id = a_scrim(app, captain)
    with app.test_request_context():
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(timespec="seconds")
        get_db().execute("UPDATE scrims SET scheduled_at = %s WHERE id = %s", (past, scrim_id))
        get_db().commit()

    assert "Scrims with no server" not in client.get("/servers").get_data(as_text=True)


def test_a_cancelled_scrim_is_not_listed_as_needing_a_server(client, app, captain):
    from app.db import get_db
    give_credits(app, captain, 2)
    scrim_id = a_scrim(app, captain)
    with app.test_request_context():
        get_db().execute("UPDATE scrims SET status = 'cancelled' WHERE id = %s", (scrim_id,))
        get_db().commit()

    assert "Scrims with no server" not in client.get("/servers").get_data(as_text=True)


def test_with_no_credits_the_attach_action_is_replaced_by_the_way_to_get_them(
        client, app, captain):
    """FR-065 again, on this surface: the scrim is still listed so the user knows it needs
    a server — but the action that would fail is not offered."""
    scrim_id = a_scrim(app, captain)

    body = client.get("/servers").get_data(as_text=True)
    assert "Scrims with no server" in body
    assert f'action="/scrims/{scrim_id}/server/attach"' not in body
    assert "Buy credits" in body


def test_another_teams_scrims_are_not_listed(client, app, captain, login, link_team):
    a_scrim(app, captain)
    outsider = login("76561198000000999", "Outsider")
    link_team(outsider, [rgl_team(4242, "Charlie", "CHR", "sixes")])

    assert "Scrims with no server" not in client.get("/servers").get_data(as_text=True)


# --- SC-004: no server ever renders without a state --------------------------------

def test_every_listed_server_shows_a_state(client, app, captain):
    """SC-004. Seeds one server in each lifecycle state and asserts each renders a label —
    an unexplained blank row is the failure mode this guards."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    states = [store.SCHEDULED, store.STARTING, store.RUNNING, store.IN_GRACE,
              store.STOPPED, store.CANCELLED, store.FAILED, store.UNKNOWN,
              store.PENDING_PAYMENT]
    with app.test_request_context():
        for state in states:
            store.create_server(
                owner_steam_id=captain, team_id=TEAM_A, name=f"srv-{state}",
                map_name="cp_x", max_slots=24, state=state,
                window_starts_at=now, window_ends_at=now)

    body = client.get("/servers").get_data(as_text=True)
    for state in states:
        assert f"srv-{state}" in body
        assert store.STATE_LABELS[state] in body, f"{state} has no visible label"
