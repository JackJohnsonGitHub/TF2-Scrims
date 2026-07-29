"""The payment state machine (T022).

Three properties carry the most weight here: crediting happens exactly once, the escrow
gate fails closed, and Steam having a bad minute never marks a payment failed.
"""
import pytest

from app import credits, payments, steam_trade
from app.payments import PaymentError
from app.steam_trade import SteamUnavailable

PAYER = "76561197972611406"          # partner 12345678
PARTNER = 12345678
TRADE_URL = f"https://steamcommunity.com/tradeoffer/new/?partner={PARTNER}&token=abc123"
KEY_NAME = "Mann Co. Supply Crate Key"


@pytest.fixture
def payer(app):
    with app.test_request_context():
        from app.accounts import upsert_on_login
        upsert_on_login(PAYER, "Payer", None)
    return PAYER


def offer(state=steam_trade.STATE_ACCEPTED, keys=2, offer_id="7000000001",
          appid=440, name=KEY_NAME, escrow_end_date=0):
    items = ((steam_trade.OfferItem(appid=appid, market_hash_name=name, amount=keys),)
             if keys else ())
    return steam_trade.TradeOffer(
        offer_id=offer_id, partner_accountid=PARTNER, state=state,
        escrow_end_date=escrow_end_date, items_to_receive=items, items_to_give=(),
    )


def no_hold(monkeypatch):
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(0, 0))


# --- trade link parsing --------------------------------------------------------------

def test_a_valid_trade_url_parses():
    assert payments.parse_trade_url(TRADE_URL) == (str(PARTNER), "abc123")


@pytest.mark.parametrize("bad, expect", [
    ("", "Paste your Steam trade URL"),
    ("https://evil.example.com/tradeoffer/new/?partner=1&token=x", "not a steamcommunity.com"),
    ("https://steamcommunity.com/profiles/123", "not a trade offer URL"),
    ("https://steamcommunity.com/tradeoffer/new/?token=x", "no valid partner id"),
    ("https://steamcommunity.com/tradeoffer/new/?partner=1", "missing its token"),
])
def test_malformed_trade_urls_are_rejected_with_the_specific_problem(bad, expect):
    with pytest.raises(PaymentError) as err:
        payments.parse_trade_url(bad)
    assert expect in str(err.value)


def test_someone_elses_trade_link_is_rejected(app, payer):
    """Storing another account's link would make the escrow pre-check report *their*
    hold status while charging this account."""
    with app.test_request_context():
        other = "https://steamcommunity.com/tradeoffer/new/?partner=999&token=abc"
        with pytest.raises(PaymentError) as err:
            payments.save_trade_link(payer, other)
        assert "different Steam account" in str(err.value)
        assert payments.get_trade_link(payer) is None


def test_a_valid_link_is_stored_and_replaceable(app, payer):
    with app.test_request_context():
        payments.save_trade_link(payer, TRADE_URL)
        link = payments.get_trade_link(payer)
        assert link["partner_id"] == str(PARTNER)
        assert link["access_token"] == "abc123"

        payments.save_trade_link(payer, TRADE_URL.replace("abc123", "zzz999"))
        assert payments.get_trade_link(payer)["access_token"] == "zzz999"


# --- the escrow gate -----------------------------------------------------------------

def test_paying_without_a_trade_link_is_refused(app, payer):
    with app.test_request_context():
        verdict = payments.check_can_pay(payer)
        assert verdict["ok"] is False
        assert verdict["fix"] == "account"


def test_a_would_be_held_trade_is_refused_before_any_trade_starts(app, payer, monkeypatch):
    """Blocking is the only way to "require Steam Guard" — Steam exposes no flag that
    makes an offer reject a sender without the mobile authenticator."""
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration",
                        lambda *a, **k: steam_trade.HoldDuration(15 * 86400, 0))
    with app.test_request_context():
        app.config["STEAM_API_KEY"] = "k"
        payments.save_trade_link(payer, TRADE_URL)
        verdict = payments.check_can_pay(payer)
        assert verdict["ok"] is False
        assert "Mobile Authenticator" in verdict["reason"]

        with pytest.raises(PaymentError):
            payments.start_payment(payer)
        assert payments.open_payment(payer) is None   # nothing was recorded


def test_the_escrow_check_fails_closed_when_steam_is_unreachable(app, payer, monkeypatch):
    """Assuming "probably no hold" risks taking keys for a server that cannot arrive in
    time, which is worse than a temporary refusal."""
    def unavailable(*a, **k):
        raise SteamUnavailable("down")
    monkeypatch.setattr(payments.steam_trade, "get_trade_hold_duration", unavailable)
    with app.test_request_context():
        app.config["STEAM_API_KEY"] = "k"
        payments.save_trade_link(payer, TRADE_URL)
        verdict = payments.check_can_pay(payer)
        assert verdict["ok"] is False
        assert "not answering" in verdict["reason"]


def test_a_clean_account_can_start_one_payment_at_a_time(app, payer, monkeypatch):
    no_hold(monkeypatch)
    with app.test_request_context():
        app.config["STEAM_API_KEY"] = "k"
        payments.save_trade_link(payer, TRADE_URL)
        row = payments.start_payment(payer)
        assert row["state"] == payments.STARTED
        assert row["items_expected"] == 2

        assert payments.check_can_pay(payer)["ok"] is False   # one at a time


# --- reconciliation ------------------------------------------------------------------

def started_payment(app, payer, monkeypatch, scrim_id=None):
    no_hold(monkeypatch)
    app.config["STEAM_API_KEY"] = "k"
    payments.save_trade_link(payer, TRADE_URL)
    return payments.start_payment(payer, target_scrim_id=scrim_id)


def test_an_accepted_offer_grants_credits(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=2))
        assert credits.available_credits(payer) == 5     # 2 keys × 2.5, floored
        assert payments.recent_payments(payer)[0]["state"] == payments.COMPLETE


def test_four_keys_grant_ten_credits(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=4))
        assert credits.available_credits(payer) == 10


def test_three_keys_floor_to_seven_credits(app, payer, monkeypatch):
    """floor(3 × 2.5) — flooring avoids carrying a fractional remainder around."""
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=3))
        assert credits.available_credits(payer) == 7


def test_reconciling_the_same_offer_twice_does_not_double_credit(app, payer, monkeypatch):
    """The exactly-once guarantee. The poller re-reads every offer on every run and can
    be run twice by hand, so this cannot depend on it behaving well."""
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=2))
        payments.reconcile_offer(offer(keys=2))
        payments.reconcile_offer(offer(keys=2))
        assert credits.available_credits(payer) == 5


def test_an_escrowed_offer_grants_nothing(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(state=steam_trade.STATE_IN_ESCROW, keys=2))
        assert credits.available_credits(payer) == 0
        assert payments.recent_payments(payer)[0]["state"] == payments.HELD


def test_an_escrowed_offer_that_later_completes_grants_once(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(state=steam_trade.STATE_IN_ESCROW, keys=2))
        payments.reconcile_offer(offer(state=steam_trade.STATE_ACCEPTED, keys=2))
        assert credits.available_credits(payer) == 5


def test_a_zero_escrow_end_date_does_not_invent_an_expiry(app, payer, monkeypatch):
    """escrow_end_date is reported as spuriously 0 (steam-for-linux#7133), so state 11
    is what we trust for "held" and no date gets fabricated from it."""
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(state=steam_trade.STATE_IN_ESCROW,
                                       keys=2, escrow_end_date=0))
        row = payments.recent_payments(payer)[0]
        assert row["state"] == payments.HELD
        assert row["hold_until"] is None


def test_too_few_keys_is_insufficient_and_says_the_shortfall(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=1))
        row = payments.recent_payments(payer)[0]
        assert row["state"] == payments.INSUFFICIENT
        assert "1" in row["state_reason"] and "2" in row["state_reason"]
        assert credits.available_credits(payer) == 0


def test_wrong_items_are_insufficient_not_failed(app, payer, monkeypatch):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(keys=20, name="Team Captain"))
        assert payments.recent_payments(payer)[0]["state"] == payments.INSUFFICIENT
        assert credits.available_credits(payer) == 0


@pytest.mark.parametrize("state", [
    steam_trade.STATE_DECLINED,
    steam_trade.STATE_CANCELED,
    steam_trade.STATE_EXPIRED,
    steam_trade.STATE_INVALID_ITEMS,
    steam_trade.STATE_CANCELED_BY_SECOND_FACTOR,
])
def test_dead_states_fail_the_payment_with_a_reason(app, payer, monkeypatch, state):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(state=state, keys=2))
        row = payments.recent_payments(payer)[0]
        assert row["state"] == payments.FAILED
        assert row["state_reason"]
        assert credits.available_credits(payer) == 0


@pytest.mark.parametrize("state", [
    steam_trade.STATE_ACTIVE,
    steam_trade.STATE_CREATED_NEEDS_CONFIRMATION,
])
def test_pending_states_leave_the_payment_alone(app, payer, monkeypatch, state):
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        payments.reconcile_offer(offer(state=state, keys=2))
        assert payments.recent_payments(payer)[0]["state"] == payments.STARTED
        assert credits.available_credits(payer) == 0


def test_a_trade_from_a_stranger_is_ignored(app, payer, monkeypatch):
    """Someone with no payment started here — perhaps no account at all. Not ours to
    credit; the operator handles it out of band."""
    with app.test_request_context():
        app.config["STEAM_API_KEY"] = "k"
        stranger = steam_trade.TradeOffer(
            offer_id="9", partner_accountid=555, state=steam_trade.STATE_ACCEPTED,
            items_to_receive=(steam_trade.OfferItem(440, KEY_NAME, 5),))
        assert payments.reconcile_offer(stranger) is None
        assert credits.available_credits(payer) == 0


# --- the poller ----------------------------------------------------------------------

def test_poll_makes_both_an_active_and_a_historical_pass(app, payer, monkeypatch):
    """THE TRAP (research R1): `Accepted` is terminal and excluded by active_only=1, so
    an active-only poller would credit nobody, silently, forever."""
    passes = []

    def fake_offers(api_key, *, active_only=True, historical_only=False,
                    time_historical_cutoff=None):
        passes.append("historical" if historical_only else "active")
        return [offer(keys=2)] if historical_only else []

    monkeypatch.setattr(payments.steam_trade, "get_received_offers", fake_offers)
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        result = payments.poll_once()

    assert set(passes) == {"active", "historical"}
    assert result["offers_seen"] == 1
    with app.test_request_context():
        assert credits.available_credits(payer) == 5


def test_poll_without_an_api_key_raises_rather_than_silently_doing_nothing(app):
    with app.test_request_context():
        app.config["STEAM_API_KEY"] = ""
        with pytest.raises(SteamUnavailable):
            payments.poll_once()


def test_steam_being_unreachable_never_fails_a_payment(app, payer, monkeypatch):
    """SC-014. A payment marked failed because Steam had a bad minute is money taken
    with nothing delivered and nothing explaining it."""
    with app.test_request_context():
        started_payment(app, payer, monkeypatch)
        before = payments.recent_payments(payer)[0]

        def unavailable(*a, **k):
            raise SteamUnavailable("429")
        monkeypatch.setattr(payments.steam_trade, "get_received_offers", unavailable)

        with pytest.raises(SteamUnavailable):
            payments.poll_once()

        after = payments.recent_payments(payer)[0]
        assert after["state"] == before["state"] == payments.STARTED
        assert credits.available_credits(payer) == 0
