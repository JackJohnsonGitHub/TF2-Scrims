# Contract: Steam trade client

**Feature**: `005-servers-page` · The seam between this app and Steam's economy API.
Signatures verified 2026-07-29 — see [research.md](../research.md) R1–R4.

Lives alongside `app/steam.py` (which already handles OpenID and persona lookup) as
`app/steam_trade.py`. Kept as a **narrow, mockable seam**: it speaks HTTP to Steam and returns plain
data. It holds no business rules — no pricing, no crediting, no state transitions. Tests mock this
module, never `requests`, so the payment logic is testable with no network.

---

## `get_trade_hold_duration(steamid64, access_token) -> HoldDuration`

Wraps `IEconService/GetTradeHoldDurations/v1`.

**Request params** — both required (this is the corrected signature; it is *not* `steamid`):

| Param | Value |
|---|---|
| `key` | `STEAM_API_KEY` |
| `steamid_target` | The user's SteamID64 |
| `trade_offer_access_token` | Token from the user's own trade URL |

**Returns**: `HoldDuration(their_seconds: int, both_seconds: int)`.

**Semantics**: `their_seconds > 0` means a trade from this user **would be held** — the caller must
refuse to start the payment (FR-042).

**Errors**: raises `SteamUnavailable` on transport failure, `429`, or a non-OK body. The caller MUST
treat that as "cannot determine" and refuse to start a payment rather than assuming no hold — failing
closed, because the cost of guessing wrong is taking money for a server that cannot be delivered.

---

## `get_received_offers(active_only, historical_cutoff=None) -> list[TradeOffer]`

Wraps `IEconService/GetTradeOffers/v1`.

**Request params**:

| Param | Value |
|---|---|
| `key` | `STEAM_API_KEY` |
| `get_received_offers` | `1` |
| `get_sent_offers` | omitted |
| `get_descriptions` | `1` |
| `language` | `english` |
| `active_only` | per argument |
| `historical_only` / `time_historical_cutoff` | per argument |

> **The trap.** `Accepted` (3) is a terminal state and is therefore excluded by `active_only=1`. A
> poller that only ever passes `active_only=1` watches offers go `Active` and then vanish, and credits
> nobody, ever. The caller MUST make a historical pass as well. This is the single most likely way to
> ship a payment loop that appears to work and never pays out.

**Returns** `TradeOffer`:

| Field | Source | Notes |
|---|---|---|
| `offer_id` | `tradeofferid` | The idempotency key. Unique in `payments`. |
| `partner_accountid` | `accountid_other` | 32-bit. |
| `partner_steamid64` | derived | `accountid_other + 76561197960265728`. |
| `state` | `trade_offer_state` | Raw enum code, mapped by the caller (research R4). |
| `escrow_end_date` | `escrow_end_date` | **Unreliable — reported as spuriously `0`.** Treat `0`/absent as "held, expiry unknown"; never render a date derived from it alone. |
| `items_to_receive` | `items_to_receive` + descriptions | Resolved to `(appid, market_hash_name, amount)`. |
| `items_to_give` | `items_to_give` | Must be **empty** — an offer asking the operator to give anything is not a payment. |

**Errors**: raises `SteamUnavailable`. The caller leaves all payment state untouched (SC-014).

---

## `count_payment_items(offer, item_name, appid) -> int`

Pure function, no network. Sums `amount` across `items_to_receive` matching both `market_hash_name`
and `appid`.

- `appid` scoping is mandatory (FR-049) — other games ship similarly-named keys.
- Non-matching items contribute **zero**; they are not an error, they simply do not count. An offer of
  20 hats is `insufficient`, not `failed`.
- An offer with a non-empty `items_to_give` returns `0` regardless of contents.

---

## Configuration

| Setting | Secret | Notes |
|---|---|---|
| `STEAM_API_KEY` | **yes** | Already plumbed but currently optional. Payment makes it load-bearing; the app MUST warn loudly at startup if payment is enabled without it, rather than failing silently at the first poll. |
| `OPERATOR_TRADE_URL` | **yes** | Contains a token. Used only as a redirect destination; never rendered into page content. |

Both come from the secret store, never source (constitution IV). Neither may be logged, and neither
may appear in an error message shown to a user.

---

## What this module must never do

- Grant, reserve, or spend credits.
- Decide whether payment was sufficient (that is `count_payment_items` plus the service layer).
- Mark a payment failed. Only the service layer transitions state, and never on a transport error.
- Log a key, a token, or a full trade URL.
