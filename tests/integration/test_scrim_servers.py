"""User Story 2: spending credits on a server while scheduling (T041, T042).

The tests that matter most here are the Principle I guards at the bottom. Feature 005
touches the free scheduling path that features 003 and 004 proved, and scheduling MUST
NEVER be blocked, delayed or rolled back by anything to do with payment.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import credits, payments, steam_trade
from app import servers_store as store
from tests.conftest import rgl_team

A = "76561198000000001"
B = "76561198000000002"
TEAM_A, TEAM_B = 101, 202


def future_iso(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def future_form(days=3):
    when = datetime.now(timezone.utc) + timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
def teams(app, client, login, link_team):
    login(A, "CaptainA")
    link_team(A, [rgl_team(TEAM_A, "Alpha", "ALP", "sixes")])
    login(B, "CaptainB")
    link_team(B, [rgl_team(TEAM_B, "Bravo", "BRV", "sixes")])


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def give_credits(app, steam_id, amount):
    with app.test_request_context():
        from app.db import get_db
        credits.grant(steam_id, amount, "test grant")
        get_db().commit()


def balance(app, steam_id):
    with app.test_request_context():
        return credits.available_credits(steam_id)


def only_scrim(app):
    with app.test_request_context():
        from app.db import get_db
        return dict(get_db().execute(
            "SELECT * FROM scrims ORDER BY id DESC LIMIT 1").fetchone())


def server_for(app, scrim_id):
    with app.test_request_context():
        return store.server_for_scrim(scrim_id)


# --- attaching while scheduling ------------------------------------------------------

def test_proposing_with_the_option_attaches_a_server(client, app, teams):
    give_credits(app, A, 5)
    as_user(client, A)

    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})

    scrim = only_scrim(app)
    server = server_for(app, scrim["id"])
    assert server is not None
    assert server["state"] == store.SCHEDULED
    assert server["owner_steam_id"] == A
    assert server["team_id"] == TEAM_A
    assert balance(app, A) == 4


def test_the_window_starts_at_the_scrims_scheduled_time(client, app, teams):
    """FR-078. Not at provisioning time: the server must be joinable when the match
    starts, and getting it ready is not the team's to pay for."""
    give_credits(app, A, 5)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})

    scrim = only_scrim(app)
    server = server_for(app, scrim["id"])
    assert server["window_starts_at"][:16] == scrim["scheduled_at"][:16]


def test_posting_a_listing_with_the_option_attaches_a_server(client, app, teams):
    give_credits(app, A, 5)
    as_user(client, A)
    client.post("/scrims/listings/new", data={
        "team_id": TEAM_A, "scheduled_at": future_form(), "use_credits": "1"})

    scrim = only_scrim(app)
    assert server_for(app, scrim["id"]) is not None
    assert balance(app, A) == 4


def test_claiming_a_listing_with_the_option_gives_the_claimer_the_server(
        client, app, teams):
    """The claimer pays, so the server must bind to the claimer's team — binding it to
    the poster's would hand visibility to the wrong side."""
    as_user(client, A)
    client.post("/scrims/listings/new", data={
        "team_id": TEAM_A, "scheduled_at": future_form()})
    scrim = only_scrim(app)

    give_credits(app, B, 5)
    as_user(client, B)
    client.post(f"/scrims/listings/{scrim['id']}/claim",
                data={"team_id": TEAM_B, "use_credits": "1"})

    server = server_for(app, scrim["id"])
    assert server is not None
    assert server["owner_steam_id"] == B
    assert server["team_id"] == TEAM_B          # the claimer's team, not the poster's
    assert balance(app, B) == 4


def test_the_option_is_hidden_without_credits(client, app, teams):
    as_user(client, A)
    for path in ("/scrims/new", "/scrims/listings/new"):
        body = client.get(path).get_data(as_text=True)
        assert 'name="use_credits"' not in body
        assert "Buy credits" in body


def test_the_option_is_offered_with_credits(client, app, teams):
    give_credits(app, A, 2)
    as_user(client, A)
    for path in ("/scrims/new", "/scrims/listings/new"):
        assert 'name="use_credits"' in client.get(path).get_data(as_text=True)


# --- attaching afterwards ------------------------------------------------------------

def test_a_server_can_be_attached_to_an_existing_scrim(client, app, teams):
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form()})
    scrim = only_scrim(app)
    assert server_for(app, scrim["id"]) is None

    give_credits(app, A, 1)
    client.post(f"/scrims/{scrim['id']}/server/attach")
    assert server_for(app, scrim["id"]) is not None
    assert balance(app, A) == 0


def test_a_scrim_cannot_get_two_servers(client, app, teams):
    give_credits(app, A, 5)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)

    client.post(f"/scrims/{scrim['id']}/server/attach", follow_redirects=True)
    assert balance(app, A) == 4          # the second attach spent nothing


def test_the_scrim_page_shows_the_attached_server_and_offers_extend(client, app, teams):
    give_credits(app, A, 5)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    with app.test_request_context():
        store.set_state(server_for(app, scrim["id"])["id"], store.RUNNING)

    body = client.get(f"/scrims/{scrim['id']}").get_data(as_text=True)
    assert "Extend 30 min — 1 credit" in body


def test_a_scrim_with_no_server_says_so_plainly(client, app, teams):
    """FR-055: never imply a server is coming when none is."""
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form()})
    scrim = only_scrim(app)

    body = client.get(f"/scrims/{scrim['id']}").get_data(as_text=True)
    assert "No server is attached" in body or "No server yet" in body


# --- credits come back when a scrim does not happen ----------------------------------

def test_cancelling_a_scrim_returns_the_reserved_credit(client, app, teams):
    give_credits(app, A, 5)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    assert balance(app, A) == 4

    as_user(client, B)
    client.post(f"/scrims/{scrim['id']}/accept")
    client.post(f"/scrims/{scrim['id']}/cancel")

    assert balance(app, A) == 5          # FR-057
    assert server_for(app, scrim["id"])["state"] == store.CANCELLED


def test_withdrawing_a_proposal_returns_the_credit(client, app, teams):
    give_credits(app, A, 3)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    client.post(f"/scrims/{scrim['id']}/withdraw")
    assert balance(app, A) == 3


def test_declining_a_proposal_returns_the_credit(client, app, teams):
    give_credits(app, A, 3)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    as_user(client, B)
    client.post(f"/scrims/{scrim['id']}/decline")
    assert balance(app, A) == 3


def test_cancelling_an_unclaimed_listing_returns_the_credit(client, app, teams):
    """FR-056: reserved against a listing nobody claimed, so it was never used."""
    give_credits(app, A, 3)
    as_user(client, A)
    client.post("/scrims/listings/new", data={
        "team_id": TEAM_A, "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    assert balance(app, A) == 2

    client.post(f"/scrims/listings/{scrim['id']}/cancel")
    assert balance(app, A) == 3


def test_a_server_that_cannot_be_placed_returns_its_credit(client, app, teams):
    """Principle VII: a team is never charged for a server it did not get, and the
    failure is visible rather than the server just being absent."""
    give_credits(app, A, 3)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    scrim = only_scrim(app)
    server = server_for(app, scrim["id"])

    with app.test_request_context():
        store.mark_failed_to_place(server["id"])

    assert balance(app, A) == 3
    assert server_for(app, scrim["id"])["state"] == store.FAILED
    body = client.get(f"/scrims/{scrim['id']}").get_data(as_text=True)
    assert "Could not be started" in body


# --- Principle I: scheduling must never be blocked by payment -----------------------

def test_scheduling_succeeds_with_a_zero_balance(client, app, teams):
    as_user(client, A)
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form()})
    assert resp.status_code == 302
    assert only_scrim(app)["status"] == "pending"


def test_posting_use_credits_with_no_balance_still_creates_the_scrim(client, app, teams):
    """The option is not rendered at zero balance, but a forged POST must not turn a
    payment problem into a scheduling failure."""
    as_user(client, A)
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    assert resp.status_code == 302

    scrim = only_scrim(app)
    assert scrim["status"] == "pending"          # the scrim exists
    assert server_for(app, scrim["id"]) is None  # and simply has no server
    assert balance(app, A) == 0


def test_scheduling_succeeds_when_steam_is_unreachable(client, app, teams, monkeypatch):
    def unavailable(*a, **k):
        raise steam_trade.SteamUnavailable("down")
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration", unavailable)
    monkeypatch.setattr(payments.steam_trade, "get_received_offers", unavailable)

    give_credits(app, A, 2)
    as_user(client, A)
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})
    assert resp.status_code == 302
    assert only_scrim(app)["status"] == "pending"


def test_scheduling_succeeds_without_a_steam_api_key(client, app, teams):
    app.config["STEAM_API_KEY"] = ""
    app.config["OPERATOR_TRADE_URL"] = ""
    as_user(client, A)
    resp = client.post("/scrims/listings/new", data={
        "team_id": TEAM_A, "scheduled_at": future_form(), "use_credits": "1"})
    assert resp.status_code == 302
    assert only_scrim(app)["status"] == "open"


def test_a_failing_reservation_never_rolls_back_the_scrim(client, app, teams,
                                                          monkeypatch):
    """The scrim is created first and unconditionally. A serverless scheduled scrim is
    a valid, honest state — not an error."""
    def boom(*a, **k):
        raise RuntimeError("reservation exploded")
    monkeypatch.setattr(store, "attach_to_scrim", boom)

    give_credits(app, A, 5)
    as_user(client, A)
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": TEAM_A, "opponent_team_id": TEAM_B,
        "scheduled_at": future_form(), "use_credits": "1"})

    assert resp.status_code == 302
    scrim = only_scrim(app)
    assert scrim["status"] == "pending"
    assert server_for(app, scrim["id"]) is None
    assert balance(app, A) == 5                  # nothing charged
