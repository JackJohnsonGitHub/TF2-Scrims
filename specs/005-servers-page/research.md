# Phase 0 Research: The Servers Page

**Feature**: `005-servers-page` · **Date**: 2026-07-29 · **Spec**: [spec.md](./spec.md)

Every Steam endpoint below was verified against live sources on 2026-07-29 rather than recalled;
one verification corrected a wrong assumption carried in from clarification (see R2).

---

## R1 — Observing the operator's received trade offers

**Decision**: Poll `IEconService/GetTradeOffers/v1` with `key`, `get_received_offers=1`,
`active_only=1`, `get_descriptions=1`, `language=english`. Reconcile every returned offer against
local payment records.

**Verified parameters** (all optional except the key):

| Parameter | Type | Use here |
|---|---|---|
| `key` | string | The operator's Web API key. Identifies *whose* offers are returned. |
| `get_received_offers` | bool | `1` — we only care about offers sent **to** the operator. |
| `get_sent_offers` | bool | omitted. |
| `get_descriptions` | bool | `1` — see R3, this is what avoids a second call. |
| `language` | string | `english`, required for `get_descriptions` to return names. |
| `active_only` | bool | `1` for the hot loop. |
| `time_historical_cutoff` | uint32 | With `active_only`, also include offers updated since a time. |
| `historical_only` | bool | For the catch-up sweep that finds offers which became `Accepted`. |

**Critical subtlety**: `active_only=1` excludes offers that have reached a terminal state — and
`Accepted` (3) *is* terminal. A poll using only `active_only` would therefore see an offer go
`Active` → vanish, and never observe the acceptance that is supposed to grant credits. The loop MUST
either pass `time_historical_cutoff` alongside `active_only`, or run a second `historical_only=1`
sweep, to catch the transition. This is the single easiest way to build a payment loop that silently
never pays out.

**Rationale**: Steam offers no webhook or callback for trade offers. Polling is the only mechanism
available, and the operator's own key is what scopes the result set to their account.

**Alternatives considered**: `IEconService/GetTradeOffer/v1` for single-offer lookup (still needs a
list call to discover ids); scraping the community trade pages (fragile, unauthenticated, against
the spirit of the API terms).

---

## R2 — The escrow pre-check, and a correction

**Decision**: Call `IEconService/GetTradeHoldDurations/v1` before offering the payment action, and
refuse to offer it when a hold would apply (spec FR-041, FR-042).

**Verified parameters — this corrects an earlier statement in this feature's clarification:**

| Parameter | Required | Notes |
|---|---|---|
| `key` | yes | Operator's key. |
| `steamid_target` | **yes** | The 64-bit SteamID of the other party. **Not** `steamid`, which is what was assumed during clarification. |
| `trade_offer_access_token` | **yes in practice** | The token from the *target user's* trade URL. Documented as omittable when the two accounts are Steam friends — which platform users will not be. |

**Response**: `my_escrow`, `their_escrow`, `both_escrow`, each carrying
`escrow_end_duration_seconds`. Nonzero `their_escrow` means a trade from that user would be held.

**Consequence for the spec — this is a real design constraint, not a detail.** The pre-check is
impossible without the user's own trade link, because the token lives inside it. So FR-044's
Accounts-page trade link cannot be "optional until they want to pay" in the loose sense; it is a
**hard precondition of offering the Trade action at all**. Ordering becomes:

> record trade link → pre-check hold duration → offer or refuse the Trade action

A user who has not saved a trade link MUST be sent to the Accounts page first, and told why. This
also makes FR-045 (explain why the link is wanted) load-bearing rather than courteous.

**Escrow rules confirmed**: a trade is held up to **15 days** unless the sender has had the Steam
Guard Mobile Authenticator enabled for **at least 7 days** with trade confirmations on. Steam Guard
itself must have been on for 15 days as a baseline. So the 15-day figure the spec reasons about is
correct, and blocking (FR-042) is the only way to "require Steam Guard", since Steam exposes no flag
to make an offer reject a non-authenticated sender.

**Known unreliability**: `escrow_end_date` on a trade offer has been reported returning `0`
spuriously (ValveSoftware/steam-for-linux#7133). Therefore: treat **state `11` (`InEscrow`) as
authoritative** for "this is held", and use `GetTradeHoldDurations` at pre-check time for
*predicting* a hold. Do not compute user-facing hold expiry from `escrow_end_date` alone; when it is
absent or zero, say "held, expiry unknown" rather than rendering a wrong date.

---

## R3 — Identifying a Mann Co. Supply Crate Key

**Decision**: Pass `get_descriptions=1&language=english` on the poll and match items on
`market_hash_name == "Mann Co. Supply Crate Key"` scoped to `appid == 440`, with the expected name
held in configuration (spec FR-051).

**Rationale**: Trade offer items carry only `appid`, `classid`, `instanceid`, `assetid`, `amount` —
no names. `get_descriptions` returns a parallel descriptions array that resolves those to display
names in the same response, which removes an entire second integration
(`ISteamEconomy/GetAssetClassInfo`) and its own failure mode.

**`appid` scoping is not optional**: other games ship items with confusingly similar names, and
spec FR-049 explicitly requires that similarly-named keys from other games not count.

**Alternatives considered**: pinning the key's `classid` as a constant — fewer moving parts and
immune to display-name changes, but opaque to read and silently wrong if Valve ever reissues the
class. Recommended as a defence-in-depth *secondary* check, not the primary one. Rejected as
primary: a hardcoded magic number no one can verify is worse than a configured name.

---

## R4 — Trade offer state machine

**Decision**: Model the provider states verbatim and map them onto the spec's payment states.

| Code | ETradeOfferState | Payment state (spec) |
|---|---|---|
| 1 | Invalid | failed |
| 2 | Active | started (awaiting the operator) |
| 3 | **Accepted** | **complete → grant credits** |
| 4 | Countered | failed |
| 5 | Expired | failed |
| 6 | Canceled | failed |
| 7 | Declined | failed |
| 8 | InvalidItems | failed |
| 9 | CreatedNeedsConfirmation | started |
| 10 | CanceledBySecondFactor | failed |
| 11 | **InEscrow** | **held** (FR-040) |

Only `3` grants credits (FR-038). `11` must never grant them until it becomes `3`.

---

## R5 — Where the polling and expiry work runs

**Decision**: A **CLI command** (`flask poll-payments`, `flask reconcile-servers`) invoked by a
**Kubernetes CronJob** in the cluster, and runnable by hand in development. No in-process scheduler.

**Rationale**: The app is served by Gunicorn with **2 sync workers**. Anything scheduled in-process
runs once per worker, so a naive APScheduler would poll Steam twice concurrently and race on
crediting the same trade — the exact failure that must not happen with money. A separate invocation
has exactly one instance by construction. A CronJob is also Kubernetes-native state (Principle III)
and matches how this repo already does out-of-band work (`scripts/seed_demo_team.py`).

**Alternatives considered**:
- *APScheduler + a database advisory lock* — workable, but adds a dependency and a lock protocol to
  get right in order to solve a problem that not sharing a process avoids entirely.
- *Poll lazily on web requests* — crediting would then depend on someone loading a page, so a team
  that paid and closed the tab stays unpaid. Rejected outright.
- *A sidecar container running a loop* — equivalent to the CronJob but keeps a process alive for work
  that is intermittent, and needs its own liveness story.

**Consequence**: crediting is eventually-consistent with a latency bounded by the CronJob interval.
The page MUST therefore show payments as "started / awaiting" honestly rather than implying instant
credit, and MUST NOT promise a credit that has not landed.

---

## R6 — SQLite concurrency (prerequisite, currently unmet)

**Decision**: Enable `journal_mode=WAL` and a `busy_timeout` on every connection before any
background writer exists.

**Finding**: `app/db.py` currently opens connections with no pragmas at all. Default SQLite journal
mode takes a **whole-database exclusive lock** for writes and the default busy timeout is **zero**,
so a concurrent writer fails immediately with `database is locked` rather than waiting. Today that
is invisible because only Gunicorn's request handlers write, briefly. The moment a poller writes
credits while a request is served, it becomes a live fault — and the symptom would be *dropped
payments*, which is the worst place for it to appear.

WAL lets readers proceed during a write and makes concurrent access viable for this workload;
`busy_timeout` converts an instant failure into a bounded wait.

**Also required**: `foreign_keys=ON`. It is off by default in SQLite, so the `REFERENCES` clauses
already in `SCHEMA` are currently decorative — worth turning on while touching this, since the credit
tables depend on referential integrity far more than the existing ones do.

**Scope note**: This is a change to shared infrastructure, not to this feature's own tables. It
should land as its own commit, before the credit work, with its own test.

---

## R7 — Crediting exactly once

**Decision**: A `payments` table keyed by the provider's own offer identifier with a **UNIQUE**
constraint on `(method, provider_ref)`, where `provider_ref` is the `tradeofferid`. Crediting and
the ledger write happen in one transaction.

**Rationale**: The poller is re-entrant by design — it re-reads the same offers on every run, and a
CronJob can overrun or be run twice by hand. Idempotency cannot rest on the poller behaving well; it
has to be enforced by the store. A unique constraint on the provider's id makes double-crediting
impossible rather than unlikely.

**Alternatives considered**: a "last processed" watermark (breaks the moment offers change state out
of order, which escrow guarantees); in-application "have I seen this?" checks (a race between two
runs).

---

## R8 — Representing a balance

**Decision**: An **append-only ledger** is the source of truth. Available balance is derived:
`granted − spent − reserved`. No cached balance column in this increment.

**Rationale**: Spec FR-068 and SC-011 require every movement to be explainable from the ledger
alone. If a cached total also exists it can disagree with the ledger, and then the ledger stops
being trustworthy for exactly the dispute it was built to settle. Volumes here are tiny — tens of
rows per account — so summing is free.

**Alternatives considered**: a `credits_balance` column on the account, updated in the same
transaction. Faster, and the standard move at scale, but it introduces a second truth for no
present benefit. Revisit only if a ledger scan ever shows up in a profile.

---

## R9 — Runtime windows, grace, and expiry

**Decision**: Store a window as `starts_at` / `ends_at` absolute timestamps plus a
`grace_used` flag, derived from the scrim's scheduled time (FR-078) and extended by explicit
extension events. A reconcile command advances state past those timestamps.

**Rationale**: Storing absolute boundaries rather than a running clock means the window is correct
without anything having to tick, which matters because the reconciler runs intermittently. A window
that a rescheduled scrim must follow (FR-082) is then a recomputation of `starts_at`, not a
migration of accumulated time.

**Grace is once per server** (FR-074): a single boolean, not a counter, so no accounting is needed.

**Charging model**: credits are reserved at attach and *spent* when the window they paid for begins
(FR-078: the clock starts at the scheduled time regardless of who connected). A server that never
started returns them (FR-067). Provisioning time is not charged (FR-079), which falls out naturally
from `starts_at` being the scrim's scheduled time rather than a provisioning completion time.

---

## R10 — Simulated provisioning

**Decision**: Replace the module-level `SAMPLE_SERVERS` list in `app/models.py` with a real
`servers` table carrying a lifecycle state, and drive state transitions from the reconciler. No
cluster calls. Demo rows keep their `demo` flag and label (FR-013).

**Rationale**: The spec's Scope-of-this-increment makes payment real and provisioning simulated. A
persisted server row with honest states is what lets the whole credit lifecycle — reserve, start,
extend, grace, stop, return — be exercised and tested end-to-end without MetalLB or RCON existing.
Feature 006 then replaces the state transitions with real cluster operations behind the same seam,
rather than rewriting the page.

**Consequence**: the `[sim]`-tagged requirements (FR-007, FR-008, FR-023, FR-025, FR-026, FR-029,
FR-030) are satisfied against simulated state. Tests must assert the *state machine*, not that a
server is genuinely reachable.

---

## R11 — Polling cadence and rate limits

**Decision**: Poll at a configurable interval, defaulting to **60 seconds**.

**Budget**: the Steam Web API terms allow **100,000 calls per day** per key. One call per minute is
1,440/day — under 1.5% of budget, leaving ample room for per-user `GetTradeHoldDurations` pre-checks
(one per payment attempt, not per page view; cache the result briefly per user).

**Caveat**: `429` responses have been reported even on lightly-used keys, so the client MUST treat
rate limiting and transport errors as *retryable and non-fatal*, leave payment state untouched, and
never mark a payment failed because Steam was unreachable (spec Assumptions; SC-014).

---

## R12 — Configuration and secrets

**Decision**: Extend the existing config seam. Nothing new is hardcoded.

| Setting | Source | Notes |
|---|---|---|
| `STEAM_API_KEY` | OpenBao → env | **Already exists** but is currently optional (personas degrade without it). Payment makes it load-bearing; startup must warn clearly when payment features are enabled without it. |
| `OPERATOR_TRADE_URL` | OpenBao → env | Contains a token; a secret by constitution IV. Never rendered into a page for anyone but as the destination of the Trade action. |
| `PAYMENT_ITEM_NAME` | config | Default `Mann Co. Supply Crate Key`. |
| `PAYMENT_ITEM_APPID` | config | Default `440`. |
| `PAYMENT_MIN_KEYS` | config | Default `2`. |
| `CREDITS_PER_KEY` | config | Default `2.5`; credits granted as `floor(keys × rate)`. |
| `CREDIT_MINUTES` | config | Default `60`. |
| `EXTENSION_MINUTES` | config | Default `30`, cost 1 credit. |
| `GRACE_MINUTES` | config | Default `15`. |
| `PAYMENT_POLL_SECONDS` | config | Default `60`. |

**Rationale**: FR-051 requires the price to move without a code change, and constitution IV requires
the credential and the operator's trade destination to come from the secret store.

---

## Resolved unknowns

| Unknown from Technical Context | Resolution |
|---|---|
| `GetTradeOffers` signature | R1 — verified; `active_only` alone is a trap |
| `GetTradeHoldDurations` signature | R2 — verified; **corrected**, needs `steamid_target` + token |
| Whether the user's trade link is optional | R2 — it is a hard precondition of paying |
| How items are identified | R3 — `get_descriptions` + name, scoped by `appid` |
| Trade state semantics | R4 — enum mapped |
| Scheduler home | R5 — CLI command + CronJob, no in-process scheduler |
| SQLite under a background writer | R6 — WAL + busy_timeout + foreign_keys, as a prerequisite |
| Double-credit safety | R7 — UNIQUE on the provider's offer id |
| Balance storage | R8 — derived from an append-only ledger |
| Expiry mechanics | R9 — absolute boundaries, reconciled |
| Rate limits | R11 — 100k/day; 60s polling is ~1.4% of budget |

No unresolved NEEDS CLARIFICATION items remain.

## Sources

- [Steam Web API/IEconService — Valve Developer Community](https://developer.valvesoftware.com/wiki/Steam_Web_API/IEconService)
- [ieconservice package — go-steam (verified GetTradeOffers parameters)](https://pkg.go.dev/github.com/lewisgibson/go-steam/api/services/ieconservice)
- [TradeOfferState — node-steam-tradeoffer-manager](https://dev.doctormckay.com/topic/2116-tradeofferstate/)
- [steamlang package — ETradeOfferState enum values](https://pkg.go.dev/github.com/an0nfunc/go-steam/v3/protocol/steamlang)
- [Mobile Authentication, Escrow, and How it affects YOU — Steam Community guide](https://steamcommunity.com/sharedfiles/filedetails?id=562532251)
- [Mobile Steam Guard trade hold 7 days or 15? — Steam Community](https://steamcommunity.com/discussions/forum/8/2860219962100338908/)
- [GetTradeOffers returns 0 for escrow_end_date randomly — ValveSoftware/steam-for-linux#7133](https://github.com/ValveSoftware/steam-for-linux/issues/7133)
- [The Ultimate Steam Web API Guide (100,000 calls/day limit)](https://zuplo.com/learning-center/what-is-the-steam-web-api)
- [Steam Web API constantly rate-limited (Error 429) — Steam Community](https://steamcommunity.com/discussions/forum/1/601902348018676495)
