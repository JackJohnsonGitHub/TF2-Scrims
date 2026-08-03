"""User Story 5 end to end: keys → credits → server time → extension (T023, T040).

Covers quickstart.md Scenario 4 and 6. Steam is mocked at the `app.steam_trade` seam,
so nothing here touches the network or needs an API key.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import credits, payments, steam_trade
from app import servers_store as store
from tests.conftest import rgl_team

PAYER = "76561197972611406"      # partner 12345678
PARTNER = 12345678
TRADE_URL = f"https://steamcommunity.com/tradeoffer/new/?partner={PARTNER}&token=abc123"
KEY_NAME = "Mann Co. Supply Crate Key"
TEAM = 101


@pytest.fixture(autouse=True)
def payment_config(app):
    app.config["STEAM_API_KEY"] = "test-key"
    app.config["OPERATOR_TRADE_URL"] = (
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=operator")


@pytest.fixture
def signed_in(app, client, login, link_team):
    steam_id = login(PAYER, "Payer")
    link_team(steam_id, [rgl_team(TEAM, "Alpha", "ALP", "sixes")])
    return steam_id


def offer(state=steam_trade.STATE_ACCEPTED, keys=2, offer_id="7000000001",
          appid=440, name=KEY_NAME):
    items = ((steam_trade.OfferItem(appid, name, keys),) if keys else ())
    return steam_trade.TradeOffer(offer_id=offer_id, partner_accountid=PARTNER,
                                 state=state, items_to_receive=items)


def mock_steam(monkeypatch, offers=(), hold_seconds=0):
    monkeypatch.setattr(steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(hold_seconds, 0))
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(hold_seconds, 0))

    def received(api_key, *, active_only=True, historical_only=False,
                 time_historical_cutoff=None):
        # Accepted is terminal, so it only shows up on the historical pass — mirroring
        # Steam, so a regression to an active-only poller fails here.
        return list(offers) if historical_only else []

    monkeypatch.setattr(payments.steam_trade, "get_received_offers", received)


def give_credits(app, steam_id, amount):
    with app.test_request_context():
        from app.db import get_db
        credits.grant(steam_id, amount, "test grant")
        get_db().commit()


# --- Scenario 1: a free account sees the free product -------------------------------

def test_a_new_account_starts_free_with_no_spend_actions(client, signed_in):
    body = client.get("/servers").get_data(as_text=True)
    assert "0 credit(s)" in body
    assert "Scheduling scrims is free" in body
    assert "Buy credits" in body


def test_the_price_is_stated_before_paying(client, signed_in):
    body = client.get("/credits").get_data(as_text=True)
    assert KEY_NAME in body
    assert "5 credits" in body                    # 2 keys → 5
    assert "60 minutes" in body                   # 1 credit → 1 hour
    assert "1 credit per 30 minutes" in body      # extension rate
    assert "15-minute grace" in body


# --- Scenario 2: the trade link is a precondition ------------------------------------

def test_paying_without_a_trade_link_points_at_the_account_page(client, signed_in):
    body = client.get("/credits").get_data(as_text=True)
    assert "need your Steam trade URL" in body
    assert "Add your trade link" in body
    assert "Start trade offer" not in body


def test_a_malformed_trade_link_is_rejected_and_not_stored(client, signed_in, app):
    resp = client.post("/account/trade-link",
                       data={"trade_url": "https://evil.example.com/x"},
                       follow_redirects=True)
    assert "not a steamcommunity.com trade URL" in resp.get_data(as_text=True)
    with app.test_request_context():
        assert payments.get_trade_link(PAYER) is None


def test_someone_elses_trade_link_is_rejected(client, signed_in):
    other = "https://steamcommunity.com/tradeoffer/new/?partner=999&token=x"
    resp = client.post("/account/trade-link", data={"trade_url": other},
                       follow_redirects=True)
    assert "different Steam account" in resp.get_data(as_text=True)


# --- Scenario 3: escrow blocks payment ----------------------------------------------

def test_a_held_trade_is_refused_and_no_trade_is_started(client, signed_in, monkeypatch,
                                                         app):
    mock_steam(monkeypatch, hold_seconds=15 * 86400)
    client.post("/account/trade-link", data={"trade_url": TRADE_URL})

    body = client.get("/credits").get_data(as_text=True)
    assert "Mobile Authenticator" in body
    assert "Start trade offer" not in body

    assert client.post("/credits/trade/start").status_code == 400
    with app.test_request_context():
        assert payments.open_payment(PAYER) is None


def test_the_gate_fails_closed_when_steam_is_unreachable(client, signed_in, monkeypatch):
    def unavailable(*a, **k):
        raise steam_trade.SteamUnavailable("down")
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration", unavailable)
    client.post("/account/trade-link", data={"trade_url": TRADE_URL})

    body = client.get("/credits").get_data(as_text=True)
    assert "not answering" in body
    assert "Start trade offer" not in body


# --- Scenario 4: payment to credits -------------------------------------------------

def start_a_payment(client, monkeypatch, offers=()):
    mock_steam(monkeypatch, offers=offers)
    client.post("/account/trade-link", data={"trade_url": TRADE_URL})
    return client.post("/credits/trade/start")


def test_starting_a_payment_redirects_to_steam_without_leaking_the_token(
        client, signed_in, monkeypatch):
    resp = start_a_payment(client, monkeypatch)
    assert resp.status_code == 302
    assert "steamcommunity.com" in resp.headers["Location"]
    # The operator's token is a secret: only ever a redirect target, never page content.
    assert "token=operator" not in client.get("/credits").get_data(as_text=True)


@pytest.mark.parametrize("keys, expected", [(2, 5), (4, 10), (3, 7)])
def test_an_accepted_trade_grants_credits(client, signed_in, monkeypatch, app,
                                          keys, expected):
    start_a_payment(client, monkeypatch, offers=[offer(keys=keys)])
    app.test_cli_runner().invoke(args=["poll-payments"])

    with app.test_request_context():
        assert credits.available_credits(PAYER) == expected
    assert f"{expected}" in client.get("/credits").get_data(as_text=True)


def test_polling_twice_does_not_double_credit(client, signed_in, monkeypatch, app):
    """The exactly-once guarantee, through the CLI the CronJob actually runs."""
    start_a_payment(client, monkeypatch, offers=[offer(keys=2)])
    runner = app.test_cli_runner()
    runner.invoke(args=["poll-payments"])
    runner.invoke(args=["poll-payments"])
    runner.invoke(args=["poll-payments"])

    with app.test_request_context():
        assert credits.available_credits(PAYER) == 5


def test_an_escrowed_trade_grants_nothing_and_says_so(client, signed_in, monkeypatch, app):
    start_a_payment(client, monkeypatch,
                    offers=[offer(state=steam_trade.STATE_IN_ESCROW, keys=2)])
    app.test_cli_runner().invoke(args=["poll-payments"])

    with app.test_request_context():
        assert credits.available_credits(PAYER) == 0
    body = client.get("/credits").get_data(as_text=True)
    assert "holding this trade" in body


def test_insufficient_keys_say_what_arrived_against_what_was_needed(
        client, signed_in, monkeypatch, app):
    start_a_payment(client, monkeypatch, offers=[offer(keys=1)])
    app.test_cli_runner().invoke(args=["poll-payments"])

    with app.test_request_context():
        assert credits.available_credits(PAYER) == 0
    body = client.get("/credits").get_data(as_text=True)
    assert "Received 1" in body and "2 needed" in body


def test_wrong_items_are_insufficient_not_failed(client, signed_in, monkeypatch, app):
    start_a_payment(client, monkeypatch, offers=[offer(keys=20, name="Team Captain")])
    app.test_cli_runner().invoke(args=["poll-payments"])
    body = client.get("/credits").get_data(as_text=True)
    assert "Not enough sent" in body


def test_steam_unreachable_leaves_every_payment_untouched(client, signed_in,
                                                          monkeypatch, app):
    start_a_payment(client, monkeypatch, offers=[offer(keys=2)])

    def unavailable(*a, **k):
        raise steam_trade.SteamUnavailable("429")
    monkeypatch.setattr(payments.steam_trade, "get_received_offers", unavailable)

    result = app.test_cli_runner().invoke(args=["poll-payments"])
    assert result.exit_code == 1                   # visible CronJob failure
    with app.test_request_context():
        assert payments.open_payment(PAYER)["state"] == payments.STARTED
        assert credits.available_credits(PAYER) == 0


def test_the_ledger_explains_every_movement(client, signed_in, monkeypatch, app):
    start_a_payment(client, monkeypatch, offers=[offer(keys=2)])
    app.test_cli_runner().invoke(args=["poll-payments"])

    body = client.get("/credits").get_data(as_text=True)
    assert "Purchased" in body
    assert f"2 × {KEY_NAME}" in body


# --- Scenario 6: runtime, grace, extension ------------------------------------------

def seed_running_server(app, steam_id, minutes_left=10, grace_used=0):
    """A server whose window ends `minutes_left` from now."""
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        return store.create_server(
            owner_steam_id=steam_id, team_id=TEAM, name="Match server",
            map_name="cp_process_final", max_slots=24, state=store.RUNNING,
            address="10.0.0.9:27015", players=12,
            window_starts_at=(now - timedelta(minutes=50)).isoformat(timespec="seconds"),
            window_ends_at=(now + timedelta(minutes=minutes_left)).isoformat(timespec="seconds"),
        )


def test_extending_adds_time_and_costs_one_credit(client, signed_in, app):
    give_credits(app, PAYER, 3)
    server_id = seed_running_server(app, PAYER, minutes_left=10)

    resp = client.post(f"/servers/{server_id}/extend", follow_redirects=True)
    assert resp.status_code == 200

    with app.test_request_context():
        assert credits.available_credits(PAYER) == 2
        assert store.minutes_remaining(store.get_server(server_id)) >= 39


def test_the_extend_action_states_its_cost_before_committing(client, signed_in, app):
    give_credits(app, PAYER, 1)
    server_id = seed_running_server(app, PAYER)
    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert "Extend 30 min — 1 credit" in body


def test_with_no_credits_the_extend_action_is_absent_but_still_refused_server_side(
        client, signed_in, app):
    """FR-065 plus T040: hiding the button is a courtesy; the route is the control."""
    server_id = seed_running_server(app, PAYER)

    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert "Extend 30 min" not in body
    assert "Buy credits" in body

    client.post(f"/servers/{server_id}/extend")
    with app.test_request_context():
        assert credits.available_credits(PAYER) == 0
        # No time was added despite the direct POST.
        assert store.minutes_remaining(store.get_server(server_id)) <= 10


def test_a_window_running_out_enters_grace_then_stops(client, signed_in, app):
    give_credits(app, PAYER, 1)
    server_id = seed_running_server(app, PAYER, minutes_left=-1)   # just expired
    runner = app.test_cli_runner()

    runner.invoke(args=["reconcile-servers"])
    with app.test_request_context():
        server = store.get_server(server_id)
        assert server["state"] == store.IN_GRACE
        assert server["grace_used"] == 1

    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert "Overtime" in body

    # Push past the grace window and reconcile again.
    with app.test_request_context():
        from app.db import get_db
        past = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat(timespec="seconds")
        get_db().execute("UPDATE servers SET window_ends_at = %s WHERE id = %s",
                         (past, server_id))
        get_db().commit()
    runner.invoke(args=["reconcile-servers"])

    with app.test_request_context():
        server = store.get_server(server_id)
        assert server["state"] == store.STOPPED
        assert server["stopped_reason"] == store.REASON_TIME_EXPIRED

    assert "Stopped because its time ran out" in client.get(
        f"/servers/{server_id}").get_data(as_text=True)


def test_extending_during_grace_returns_the_server_to_running(client, signed_in, app):
    give_credits(app, PAYER, 2)
    server_id = seed_running_server(app, PAYER, minutes_left=-1)
    runner = app.test_cli_runner()
    runner.invoke(args=["reconcile-servers"])          # → in_grace

    client.post(f"/servers/{server_id}/extend")
    with app.test_request_context():
        server = store.get_server(server_id)
        assert server["state"] == store.RUNNING
        assert credits.available_credits(PAYER) == 1


def test_the_grace_is_once_per_server_not_once_per_window(client, signed_in, app):
    """Granting it per window would quietly make every credit buy 45 minutes."""
    give_credits(app, PAYER, 5)
    server_id = seed_running_server(app, PAYER, minutes_left=-1, grace_used=0)
    runner = app.test_cli_runner()
    runner.invoke(args=["reconcile-servers"])          # first grace
    client.post(f"/servers/{server_id}/extend")        # back to running

    with app.test_request_context():
        from app.db import get_db
        past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(timespec="seconds")
        get_db().execute("UPDATE servers SET window_ends_at = %s, state = %s WHERE id = %s",
                         (past, store.RUNNING, server_id))
        get_db().commit()
    runner.invoke(args=["reconcile-servers"])

    with app.test_request_context():
        # No second grace: straight to stopped.
        assert store.get_server(server_id)["state"] == store.STOPPED


def test_reconciling_twice_changes_nothing_extra(client, signed_in, app):
    give_credits(app, PAYER, 1)
    server_id = seed_running_server(app, PAYER, minutes_left=-1)
    runner = app.test_cli_runner()
    runner.invoke(args=["reconcile-servers"])
    runner.invoke(args=["reconcile-servers"])
    runner.invoke(args=["reconcile-servers"])

    with app.test_request_context():
        assert store.get_server(server_id)["state"] == store.IN_GRACE
        assert credits.available_credits(PAYER) == 1    # idempotent, nothing spent


def test_extending_a_stopped_server_is_refused(client, signed_in, app):
    give_credits(app, PAYER, 2)
    server_id = seed_running_server(app, PAYER)
    with app.test_request_context():
        store.set_state(server_id, store.STOPPED,
                        stopped_reason=store.REASON_TIME_EXPIRED)

    client.post(f"/servers/{server_id}/extend")
    with app.test_request_context():
        assert credits.available_credits(PAYER) == 2    # nothing charged


def test_a_teammate_who_is_not_the_owner_cannot_extend(client, app, login, link_team):
    # The owner's account and the team both have to exist before a server can reference
    # them — foreign keys are enforced as of feature 005.
    owner = login(PAYER, "Owner")
    link_team(owner, [rgl_team(TEAM, "Alpha", "ALP", "sixes")])
    give_credits(app, owner, 2)
    server_id = seed_running_server(app, owner)

    mate = login("76561198000000777", "Teammate")
    link_team(mate, [rgl_team(TEAM, "Alpha", "ALP", "sixes")])

    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert "Extend 30 min" not in body
    assert client.post(f"/servers/{server_id}/extend").status_code == 404


# --- FR-020: a target scrim that will not happen ------------------------------------

def _scrim(app, steam_id, status="open", days=2):
    from app.db import get_db
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        db = get_db()
        cur = db.execute(
            """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                   status, created_by, created_at, updated_at)
               VALUES ('sixes', %s, 'listing', %s, %s, %s, %s, %s)
               RETURNING id""",
            ((now + timedelta(days=days)).isoformat(timespec="seconds"), TEAM, status,
             steam_id, now.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")))
        scrim_id = cur.fetchone()["id"]
        db.commit()
        return scrim_id


def _start_for_scrim(client, monkeypatch, scrim_id):
    mock_steam(monkeypatch)
    client.post("/account/trade-link", data={"trade_url": TRADE_URL})
    return client.post("/credits/trade/start", data={"scrim_id": scrim_id})


def test_a_live_target_scrim_produces_no_warning(client, signed_in, app, monkeypatch):
    scrim_id = _scrim(app, PAYER)
    _start_for_scrim(client, monkeypatch, scrim_id)

    body = client.get("/credits").get_data(as_text=True)
    assert "called off" not in body
    assert "already started" not in body


def test_a_cancelled_target_scrim_is_reported_without_killing_the_payment(
        client, signed_in, app, monkeypatch):
    """FR-020. The scrim is gone; the payment is not. Credits are not scrim-bound, so
    telling the payer their payment died with the scrim would be wrong and alarming."""
    from app.db import get_db
    scrim_id = _scrim(app, PAYER)
    _start_for_scrim(client, monkeypatch, scrim_id)

    with app.test_request_context():
        get_db().execute("UPDATE scrims SET status = 'cancelled' WHERE id = %s", (scrim_id,))
        get_db().commit()

    body = client.get("/credits").get_data(as_text=True)
    assert "has been called off" in body
    assert "still arrive" in body                    # the payment stands

    with app.test_request_context():
        assert payments.open_payment(PAYER)["state"] == payments.STARTED


def test_a_past_target_scrim_is_reported(client, signed_in, app, monkeypatch):
    from app.db import get_db
    scrim_id = _scrim(app, PAYER)
    _start_for_scrim(client, monkeypatch, scrim_id)

    with app.test_request_context():
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
        get_db().execute("UPDATE scrims SET scheduled_at = %s WHERE id = %s", (past, scrim_id))
        get_db().commit()

    assert "has already started" in client.get("/credits").get_data(as_text=True)


def test_a_stale_target_still_credits_normally(client, signed_in, app, monkeypatch):
    """The whole point of the amendment: the credits land regardless."""
    from app.db import get_db
    scrim_id = _scrim(app, PAYER)
    mock_steam(monkeypatch, offers=[offer(keys=2)])
    client.post("/account/trade-link", data={"trade_url": TRADE_URL})
    client.post("/credits/trade/start", data={"scrim_id": scrim_id})

    with app.test_request_context():
        get_db().execute("UPDATE scrims SET status = 'cancelled' WHERE id = %s", (scrim_id,))
        get_db().commit()

    app.test_cli_runner().invoke(args=["poll-payments"])
    with app.test_request_context():
        assert credits.available_credits(PAYER) == 5


def test_a_payment_with_no_target_scrim_is_never_flagged(client, signed_in, monkeypatch):
    start_a_payment(client, monkeypatch)
    body = client.get("/credits").get_data(as_text=True)
    assert "no longer exists" not in body
    assert "called off" not in body


def test_a_payment_is_not_visible_to_a_teammate(client, app, login, link_team,
                                                monkeypatch):
    """FR-018 as amended: a payment belongs to the account that made it. What a team
    needs to see is the server it produces, not its captain's payment record."""
    signed = login(PAYER, "Payer")
    link_team(signed, [rgl_team(TEAM, "Alpha", "ALP", "sixes")])
    app.config["STEAM_API_KEY"] = "test-key"
    app.config["OPERATOR_TRADE_URL"] = (
        "https://steamcommunity.com/tradeoffer/new/?partner=1&token=operator")
    start_a_payment(client, monkeypatch)

    mate = login("76561198000000888", "Teammate")
    link_team(mate, [rgl_team(TEAM, "Alpha", "ALP", "sixes")])

    body = client.get("/credits").get_data(as_text=True)
    assert "payment in progress" not in body
    assert "Start trade offer" not in body or "trade URL" in body


# --- the header credit box ----------------------------------------------------------

def test_the_header_shows_the_credit_balance_on_every_page(client, signed_in, app):
    """Credits gate whether a scrim can have a server, so the balance belongs somewhere
    always visible — not only on /credits."""
    give_credits(app, PAYER, 7)

    for path in ("/", "/servers", "/scrims", "/account", "/credits"):
        body = client.get(path).get_data(as_text=True)
        assert 'class="credit-box' in body, f"no credit box on {path}"
        assert ">7<" in body, f"balance missing on {path}"


def test_the_empty_state_prompts_rather_than_receding(client, signed_in, app):
    """A zero balance is when this most needs to be noticed, so it keeps full contrast
    and says what to do instead of just reading "0"."""
    body = client.get("/servers").get_data(as_text=True)
    assert "credit-box-empty" in body
    assert ">0<" in body
    assert "buy credits" in body               # a prompt, not a bare number

    give_credits(app, PAYER, 1)
    body = client.get("/servers").get_data(as_text=True)
    assert "credit-box-empty" not in body
    assert ">credit<" in body                  # singular at exactly one


def test_the_box_links_to_the_credits_page(client, signed_in, app):
    give_credits(app, PAYER, 3)
    body = client.get("/servers").get_data(as_text=True)
    assert 'class="credit-box' in body and 'href="/credits"' in body


def test_anonymous_visitors_get_no_credit_box_and_no_query(client, monkeypatch):
    """The landing page must do no database work for a visitor who has no account."""
    from app import credits as credits_module

    def boom(*a, **k):
        raise AssertionError("anonymous pages must not read the ledger")
    monkeypatch.setattr(credits_module, "available_credits", boom)

    body = client.get("/").get_data(as_text=True)
    assert "credit-box" not in body


def test_the_404_page_renders_for_a_signed_in_user(client, signed_in):
    """The context processor runs on error pages too, so it must not blow up there."""
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert 'data-screen="not-found"' in resp.get_data(as_text=True)
