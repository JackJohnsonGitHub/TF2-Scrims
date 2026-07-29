"""Steam economy API seam: trade hold durations and received trade offers.

Deliberately separate from `app/steam.py`. OpenID sign-in and the economy API share a
vendor and nothing else, and keeping them apart is what lets tests mock payment without
touching authentication.

This module speaks HTTP to Steam and returns plain data. It holds **no business rules** —
no pricing, no crediting, no state transitions. Tests mock this module rather than
`requests`, so the payment logic is exercised with no network and no API key.

Signatures verified against live sources on 2026-07-29; see
specs/005-servers-page/research.md R1-R4.
"""
from dataclasses import dataclass, field

import requests

ECON_BASE = "https://api.steampowered.com/IEconService"
_HTTP_TIMEOUT = 10

# SteamID64 = 32-bit account id + this. The `partner` value in a trade URL is that same
# 32-bit id, which is what lets an incoming offer be attributed to an account.
STEAMID64_BASE = 76561197960265728

# ETradeOfferState. Only ACCEPTED grants credits; IN_ESCROW must never.
STATE_INVALID = 1
STATE_ACTIVE = 2
STATE_ACCEPTED = 3
STATE_COUNTERED = 4
STATE_EXPIRED = 5
STATE_CANCELED = 6
STATE_DECLINED = 7
STATE_INVALID_ITEMS = 8
STATE_CREATED_NEEDS_CONFIRMATION = 9
STATE_CANCELED_BY_SECOND_FACTOR = 10
STATE_IN_ESCROW = 11

# States that mean "still waiting on the operator or the sender".
PENDING_STATES = (STATE_ACTIVE, STATE_CREATED_NEEDS_CONFIRMATION)
# Terminal states that are not a completed payment.
DEAD_STATES = (STATE_INVALID, STATE_COUNTERED, STATE_EXPIRED, STATE_CANCELED,
               STATE_DECLINED, STATE_INVALID_ITEMS, STATE_CANCELED_BY_SECOND_FACTOR)

DEAD_STATE_REASONS = {
    STATE_INVALID: "Steam rejected the offer as invalid.",
    STATE_COUNTERED: "The offer was countered rather than accepted.",
    STATE_EXPIRED: "The offer expired before it was accepted.",
    STATE_CANCELED: "The offer was cancelled.",
    STATE_DECLINED: "The offer was declined.",
    STATE_INVALID_ITEMS: "Some items in the offer were no longer valid.",
    STATE_CANCELED_BY_SECOND_FACTOR: "The offer was cancelled by Steam Guard.",
}


class SteamUnavailable(RuntimeError):
    """Steam could not be reached, rate-limited us, or answered unusably.

    Callers MUST treat this as "cannot determine" — never as a failed payment. A
    payment marked failed because Steam had a bad minute is money taken with nothing
    delivered and nothing explaining it.
    """


def steamid64_from_accountid(accountid) -> str:
    return str(int(accountid) + STEAMID64_BASE)


def accountid_from_steamid64(steamid64) -> int:
    return int(steamid64) - STEAMID64_BASE


@dataclass(frozen=True)
class HoldDuration:
    """Predicted escrow, in seconds. `their_seconds > 0` means a trade from this user
    would be held and the payment must be refused up front."""

    their_seconds: int
    both_seconds: int

    @property
    def would_be_held(self) -> bool:
        return self.their_seconds > 0 or self.both_seconds > 0

    @property
    def days(self) -> int:
        return max(self.their_seconds, self.both_seconds) // 86400


@dataclass(frozen=True)
class OfferItem:
    appid: int
    market_hash_name: str
    amount: int


@dataclass(frozen=True)
class TradeOffer:
    offer_id: str
    partner_accountid: int
    state: int
    escrow_end_date: int = 0
    items_to_receive: tuple = field(default_factory=tuple)
    items_to_give: tuple = field(default_factory=tuple)

    @property
    def partner_steamid64(self) -> str:
        return steamid64_from_accountid(self.partner_accountid)

    @property
    def asks_us_to_give(self) -> bool:
        """An offer wanting the operator to hand something over is not a payment."""
        return bool(self.items_to_give)


def _get(path: str, params: dict) -> dict:
    try:
        resp = requests.get(f"{ECON_BASE}/{path}", params=params, timeout=_HTTP_TIMEOUT)
    except requests.RequestException as exc:
        raise SteamUnavailable(f"{path} unreachable") from exc
    # 429 included deliberately: rate limiting is a transient condition, not a verdict
    # on anyone's payment.
    if resp.status_code != 200:
        raise SteamUnavailable(f"{path} returned HTTP {resp.status_code}")
    try:
        return resp.json().get("response", {}) or {}
    except ValueError as exc:
        raise SteamUnavailable(f"{path} returned unparseable JSON") from exc


def get_trade_hold_duration(api_key: str, steamid64: str,
                            access_token: str) -> HoldDuration:
    """Would a trade from this user be held?

    The parameter is `steamid_target`, not `steamid`, and `trade_offer_access_token` is
    required in practice — Steam documents it as omittable only between accounts that
    are already friends, which platform users will not be. That token exists only
    inside the user's own trade URL, which is why recording that URL is a precondition
    of paying rather than a convenience.
    """
    data = _get("GetTradeHoldDurations/v1/", {
        "key": api_key,
        "steamid_target": steamid64,
        "trade_offer_access_token": access_token,
    })
    their = int((data.get("their_escrow") or {}).get("escrow_end_duration_seconds", 0))
    both = int((data.get("both_escrow") or {}).get("escrow_end_duration_seconds", 0))
    return HoldDuration(their_seconds=their, both_seconds=both)


def _index_descriptions(raw: list) -> dict:
    """(classid, instanceid) → description, so item names can be resolved from the
    same response rather than by a second API call."""
    out = {}
    for d in raw or []:
        key = (str(d.get("classid")), str(d.get("instanceid", "0")))
        out[key] = d
    return out


def _items(raw: list, descriptions: dict) -> tuple:
    items = []
    for entry in raw or []:
        key = (str(entry.get("classid")), str(entry.get("instanceid", "0")))
        desc = descriptions.get(key, {})
        items.append(OfferItem(
            appid=int(entry.get("appid", 0)),
            # market_hash_name is the stable identifier; `name` is the display fallback.
            market_hash_name=desc.get("market_hash_name") or desc.get("name") or "",
            amount=int(entry.get("amount", 1)),
        ))
    return tuple(items)


def get_received_offers(api_key: str, *, active_only: bool = True,
                        historical_only: bool = False,
                        time_historical_cutoff: int | None = None) -> list[TradeOffer]:
    """Trade offers sent *to* the account that owns `api_key`.

    `get_descriptions=1` with a language is what makes item names available inline;
    without it items are only classids and identifying a key needs a second call.

    **The trap** (research R1): `Accepted` is a terminal state, so `active_only=1`
    excludes it. A poller that only ever passes `active_only` watches offers go Active
    and then vanish, and credits nobody — silently, forever. Callers must also make a
    historical pass; `payments.poll_once` does.
    """
    params = {
        "key": api_key,
        "get_received_offers": 1,
        "get_descriptions": 1,
        "language": "english",
    }
    if historical_only:
        params["historical_only"] = 1
    else:
        params["active_only"] = 1 if active_only else 0
        if time_historical_cutoff is not None:
            params["time_historical_cutoff"] = time_historical_cutoff

    data = _get("GetTradeOffers/v1/", params)
    descriptions = _index_descriptions(data.get("descriptions"))
    offers = []
    for raw in data.get("trade_offers_received") or []:
        offers.append(TradeOffer(
            offer_id=str(raw.get("tradeofferid")),
            partner_accountid=int(raw.get("accountid_other", 0)),
            state=int(raw.get("trade_offer_state", STATE_INVALID)),
            # Reported as spuriously 0 (steam-for-linux#7133), so state 11 is what we
            # trust for "held" and this is only used to show an expiry when present.
            escrow_end_date=int(raw.get("escrow_end_date") or 0),
            items_to_receive=_items(raw.get("items_to_receive"), descriptions),
            items_to_give=_items(raw.get("items_to_give"), descriptions),
        ))
    return offers


def count_payment_items(offer: TradeOffer, item_name: str, appid: int) -> int:
    """How many of the accepted item this offer actually contains. Pure; no network.

    Scoping by `appid` is mandatory, not defensive: other games ship items with
    confusingly similar names and FR-049 requires they not count. Non-matching items
    contribute zero rather than being an error — an offer of twenty hats is
    insufficient payment, not a failure.
    """
    if offer.asks_us_to_give:
        return 0
    return sum(i.amount for i in offer.items_to_receive
               if i.appid == appid and i.market_hash_name == item_name)
