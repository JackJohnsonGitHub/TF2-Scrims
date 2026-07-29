"""The Steam economy API seam (T021, T024).

Signatures verified live on 2026-07-29 — see specs/005-servers-page/research.md R1-R4.
These tests pin the request shapes because getting one wrong fails silently rather than
loudly: the wrong parameter name returns a valid-looking empty response.
"""
import pytest
import requests

from app import steam_trade
from app.steam_trade import SteamUnavailable


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload or {}
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


def capture(monkeypatch, payload=None, status_code=200, bad_json=False):
    """Record the params of every outgoing call and answer with `payload`."""
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append({"url": url, "params": params or {}})
        return FakeResponse(status_code, payload, bad_json)

    monkeypatch.setattr(steam_trade.requests, "get", fake_get)
    return calls


KEY_NAME = "Mann Co. Supply Crate Key"


def offer_payload(state=steam_trade.STATE_ACCEPTED, keys=2, accountid=104898176,
                  offer_id="7000000001", appid=440, name=KEY_NAME, give=None,
                  escrow_end_date=0):
    """One received offer, shaped the way GetTradeOffers returns them: items carry
    classids only, and names come from a parallel descriptions array."""
    items = [{"appid": appid, "classid": "101", "instanceid": "0", "amount": keys}] if keys else []
    return {
        "response": {
            "trade_offers_received": [{
                "tradeofferid": offer_id,
                "accountid_other": accountid,
                "trade_offer_state": state,
                "escrow_end_date": escrow_end_date,
                "items_to_receive": items,
                "items_to_give": give or [],
            }],
            "descriptions": [
                {"appid": appid, "classid": "101", "instanceid": "0",
                 "market_hash_name": name},
            ],
        }
    }


# --- steamid mapping -----------------------------------------------------------------

def test_accountid_maps_to_steamid64_and_back():
    # The `partner` in a trade URL is the same 32-bit id as `accountid_other`, which is
    # what makes attributing an incoming trade to an account possible at all.
    assert steam_trade.steamid64_from_accountid(104898176) == "76561198065163904"
    assert steam_trade.accountid_from_steamid64("76561198065163904") == 104898176


# --- GetTradeHoldDurations -----------------------------------------------------------

def test_hold_duration_sends_steamid_target_and_the_access_token(monkeypatch):
    """The parameter is `steamid_target`, NOT `steamid`, and the token is required —
    it lives inside the user's own trade URL, which is why recording that URL is a
    precondition of paying."""
    calls = capture(monkeypatch, {"response": {
        "their_escrow": {"escrow_end_duration_seconds": 0},
        "both_escrow": {"escrow_end_duration_seconds": 0}}})

    steam_trade.get_trade_hold_duration("KEY", "76561198065163904", "tok123")

    params = calls[0]["params"]
    assert params["steamid_target"] == "76561198065163904"
    assert params["trade_offer_access_token"] == "tok123"
    assert params["key"] == "KEY"
    assert "steamid" not in params


def test_no_hold_is_reported_as_no_hold(monkeypatch):
    capture(monkeypatch, {"response": {
        "their_escrow": {"escrow_end_duration_seconds": 0},
        "both_escrow": {"escrow_end_duration_seconds": 0}}})
    hold = steam_trade.get_trade_hold_duration("KEY", "1", "t")
    assert hold.would_be_held is False


def test_a_fifteen_day_hold_is_detected_with_its_length(monkeypatch):
    capture(monkeypatch, {"response": {
        "their_escrow": {"escrow_end_duration_seconds": 15 * 86400},
        "both_escrow": {"escrow_end_duration_seconds": 0}}})
    hold = steam_trade.get_trade_hold_duration("KEY", "1", "t")
    assert hold.would_be_held is True
    assert hold.days == 15


def test_transport_failure_raises_steam_unavailable(monkeypatch):
    def boom(*a, **k):
        raise requests.RequestException("connection reset")
    monkeypatch.setattr(steam_trade.requests, "get", boom)
    with pytest.raises(SteamUnavailable):
        steam_trade.get_trade_hold_duration("KEY", "1", "t")


def test_rate_limiting_raises_steam_unavailable(monkeypatch):
    """429 is a transient condition, not a verdict on anyone's payment."""
    capture(monkeypatch, status_code=429)
    with pytest.raises(SteamUnavailable):
        steam_trade.get_trade_hold_duration("KEY", "1", "t")


def test_unparseable_json_raises_steam_unavailable(monkeypatch):
    capture(monkeypatch, bad_json=True)
    with pytest.raises(SteamUnavailable):
        steam_trade.get_received_offers("KEY")


# --- GetTradeOffers ------------------------------------------------------------------

def test_received_offers_request_shape(monkeypatch):
    calls = capture(monkeypatch, offer_payload())
    steam_trade.get_received_offers("KEY")
    params = calls[0]["params"]
    assert params["get_received_offers"] == 1
    assert params["get_descriptions"] == 1      # avoids a second call for item names
    assert params["language"] == "english"      # required for descriptions to resolve
    assert "get_sent_offers" not in params


def test_historical_pass_does_not_send_active_only(monkeypatch):
    """THE TRAP (research R1). `Accepted` is terminal, so active_only=1 excludes it.
    A poller that only ever passes active_only watches offers go Active and then
    vanish, and credits nobody — silently, forever."""
    calls = capture(monkeypatch, offer_payload())
    steam_trade.get_received_offers("KEY", historical_only=True)
    params = calls[0]["params"]
    assert params["historical_only"] == 1
    assert "active_only" not in params


def test_offers_are_parsed_with_names_resolved_from_descriptions(monkeypatch):
    capture(monkeypatch, offer_payload(keys=2))
    offers = steam_trade.get_received_offers("KEY")
    assert len(offers) == 1
    offer = offers[0]
    assert offer.offer_id == "7000000001"
    assert offer.state == steam_trade.STATE_ACCEPTED
    assert offer.partner_steamid64 == "76561198065163904"
    assert offer.items_to_receive[0].market_hash_name == KEY_NAME
    assert offer.items_to_receive[0].amount == 2


def test_an_empty_response_is_not_an_error(monkeypatch):
    capture(monkeypatch, {"response": {}})
    assert steam_trade.get_received_offers("KEY") == []


# --- count_payment_items -------------------------------------------------------------

def _offer(**kw):
    import app.steam_trade as st
    capture_payload = offer_payload(**kw)["response"]["trade_offers_received"][0]
    descriptions = st._index_descriptions(offer_payload(**kw)["response"]["descriptions"])
    return st.TradeOffer(
        offer_id=capture_payload["tradeofferid"],
        partner_accountid=capture_payload["accountid_other"],
        state=capture_payload["trade_offer_state"],
        items_to_receive=st._items(capture_payload["items_to_receive"], descriptions),
        items_to_give=st._items(capture_payload["items_to_give"], descriptions),
    )


def test_counting_keys():
    assert steam_trade.count_payment_items(_offer(keys=2), KEY_NAME, 440) == 2
    assert steam_trade.count_payment_items(_offer(keys=5), KEY_NAME, 440) == 5


def test_keys_from_another_game_do_not_count():
    """FR-049. Other games ship items with confusingly similar names, so appid scoping
    is mandatory rather than defensive."""
    other_game = _offer(keys=10, appid=730)
    assert steam_trade.count_payment_items(other_game, KEY_NAME, 440) == 0


def test_non_matching_items_count_zero_rather_than_erroring():
    """An offer of twenty hats is insufficient payment, not a failure."""
    hats = _offer(keys=20, name="Team Captain")
    assert steam_trade.count_payment_items(hats, KEY_NAME, 440) == 0


def test_an_offer_asking_us_to_give_something_counts_zero():
    """Not a payment — somebody wanting items *from* the operator."""
    grabby = _offer(keys=2, give=[{"appid": 440, "classid": "101",
                                   "instanceid": "0", "amount": 1}])
    assert grabby.asks_us_to_give is True
    assert steam_trade.count_payment_items(grabby, KEY_NAME, 440) == 0


def test_an_empty_offer_counts_zero():
    assert steam_trade.count_payment_items(_offer(keys=0), KEY_NAME, 440) == 0
