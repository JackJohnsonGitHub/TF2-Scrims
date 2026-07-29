# Contract: Servers, payment, and credit routes

**Feature**: `005-servers-page` · Follows the convention of
[`004/contracts/dashboard-routes.md`](../../004-scrims-dashboard/contracts/dashboard-routes.md).

All routes require an authenticated session (`@login_required`, FR-003). Every route that resolves a
server does so through an access check and returns **404, never 403**, for a server the viewer may not
see (FR-002) — an inaccessible server must be indistinguishable from a nonexistent one.

Mutating routes accept a `next` field guarded by `safe_next`, matching the pattern established in
`d72d501`, so acting from a scrim page returns you to that scrim page.

---

## Existing routes, changed

### `GET /servers` — the Servers page

Renders `servers_list.html`. Replaces the placeholder table.

**Context**: `servers` (accessible, with live state and window), `balance` (available credits),
`payment` (the viewer's in-flight payment, if any), `trade_link` (present or absent),
`scrims_without_servers` (FR-016), `price` (the configured rate, FR-071).

**Behaviour**:
- Unlinked RGL viewer → link prompt, no inventory, no request form (FR-004).
- No servers and no credits → empty state stating scheduling is free and how to buy (FR-012).
- `balance == 0` → **no credit-spending action is rendered at all**; the route to buying credits
  appears instead (FR-065).
- Every server shows a state; running ones show address and join password (FR-005–FR-008).

### `GET /servers/<id>` — server detail

Unchanged shape; now reads a persisted server. Adds time remaining (FR-062), the extend action when
affordable, and the grace warning when `state = in_grace` (FR-075).

### `POST /servers/<id>/settings`

Unchanged contract. Now persists (FR-023). `[sim]` — applied to simulated state.

Rejects per-field with `400` and no partial application (FR-024).

### `POST /servers/<id>/console`

Unchanged contract. `[sim]` — still a placeholder response, but now refuses when the server is not
`running`, with the reason stated (FR-026), rather than always answering.

### **Removed**: `GET|POST /servers/new`

Self-service creation is no longer a thing that exists (FR-014). The route, `server_new.html`, the
`nav-cta` in `base.html:18`, and the dashboard link in `dashboard.html:23` all go.

> **Breaking**: `tests/integration/test_routes.py::test_create_server_form_renders` asserts this form
> renders, and `001`'s spec required it. Both are superseded by constitution v3.1.0 Principle VIII —
> there is no user-completable path to creating a server. The test is replaced by one asserting the
> route is gone and the nav no longer offers it.

---

## New routes — payment and credits

### `POST /credits/trade/start`

Begins a payment (FR-032).

**Preconditions, in order** — each failure has its own message:
1. Trade link on file, else redirect to `/account` explaining why it is needed (research R2 — the
   pre-check is impossible without the token).
2. `GetTradeHoldDurations` reports no hold for this user, else **refuse** and explain Steam Guard
   Mobile (FR-041, FR-042). No trade is started.
3. No payment already `started` for this user.

**On success**: creates a `payments` row in `started`, optionally with `target_scrim_id`, and
redirects the browser to the operator's trade URL (never rendering that URL's token into the page).

**Returns**: `302` to Steam on success; `400` with the reason on a precondition failure.

### `GET /credits`

The balance and ledger view (FR-059, FR-068, SC-011). Every grant, reserve, release, spend and
extension with its cause. Read-only.

Also annotates each payment whose target scrim is no longer applicable — cancelled, declined, or
already past (FR-020). The payment itself stays valid: credits are not scrim-bound, so a stale
target costs the payer nothing, and they are told the credits can be spent elsewhere.

### `POST /credits/cancel/<payment_id>`

Abandon a payment that was started but never sent, so the one-at-a-time rule in
`/credits/trade/start` does not strand the user.

Only valid while **no Steam offer has been attached**. Once an offer exists, Steam's state decides
the outcome; letting a user overwrite that would be a way to disown a trade the operator already
accepted.

### `POST /servers/<id>/extend`

Buys `EXTENSION_MINUTES` for 1 credit (FR-063).

- `404` if the viewer may not access the server.
- `403`-equivalent (rendered refusal) if the viewer is not the owner (FR-027).
- **Not rendered at all** when `balance < 1` (FR-065) — but still re-checked server-side, because an
  un-rendered action is not a security control.
- Refuses when the server is not `running` or `in_grace`.
- Extends `window_ends_at`, writes an `extend` ledger row, keeps the server running with no
  interruption to players (FR-077).
- Shows cost and added time before committing (FR-081).

### `POST /scrims/<id>/server/attach`

Attaches a server to an already-scheduled scrim from the Servers page or the scrim's page (FR-015).

Reserves 1 credit, creates a `servers` row in `scheduled` with the window derived from the scrim's
scheduled time. `409` if that scrim already has a server (FR-058, FR-017).

---

## Changed routes — attaching while scheduling

Three existing scrim routes gain one optional field, `use_credits` (FR-052).

| Route | Change |
|---|---|
| `POST /scrims/propose` (propose) | Optional `use_credits`. The form itself is `GET /scrims/new`. |
| `POST /scrims/listings/new` (post a listing) | Optional `use_credits`. |
| `POST /scrims/<id>/claim` (claim a listing) | Optional `use_credits`. |

**Behaviour for all three** — and the ordering here is the whole of Principle I:

1. **Create the scrim first, unconditionally.** Scheduling MUST NEVER fail, be delayed, or be rolled
   back because of payment, balance, or Steam being unreachable (FR-054, SC-014).
2. Then, if `use_credits` was set:
   - sufficient balance → reserve 1 credit, create the server in `scheduled`;
   - insufficient → create the server in `pending_payment` and redirect to payment with
     `target_scrim_id` set.
3. The field is **not rendered** when `balance < 1` (FR-065); the route ignores it if submitted
   anyway, and the scrim is still created.

> The scrim's creation and the credit reservation MUST NOT share a transaction whose failure can
> abort the scrim. A failed reservation leaves a scheduled scrim with no server, which is a valid,
> honest state (FR-055) — not an error.

### `GET /scrims/<id>` — scrim detail

Adds: whether a server is attached and its state; the extend action for the attached server
(FR-080); and, when the option was chosen but never paid for, a plain statement that **no server is
attached** rather than any implication that one is coming (FR-055).

---

## Account page

### `POST /account/trade-link`

Records or replaces the viewer's trade URL (FR-044), rendered beneath RGL linking in
`account.html`.

- Parses `partner` and `token`; rejects a malformed link per-field without storing (FR-046).
- Rejects a link whose `partner` does not resolve to the signed-in SteamID64 — otherwise the escrow
  pre-check would answer about somebody else.
- States why the link is wanted: the escrow pre-check and any return of items (FR-045).

### `POST /account/trade-link/delete`

Removes the stored trade link. Payment then refuses at its first precondition until a new one is
saved, because the escrow pre-check has no token to work with.

---

## CLI contracts (not HTTP)

Invoked by Kubernetes CronJobs in the cluster and by hand in development (research R5). One instance
at a time by construction — never scheduled in-process, because Gunicorn's two workers would race on
crediting the same trade.

### `flask poll-payments`

1. `GetTradeOffers` with `get_received_offers=1&get_descriptions=1&language=english`, using **both**
   an `active_only` pass and a historical pass — `Accepted` is terminal and is excluded by
   `active_only` alone, so a loop without the second pass would never credit anyone (research R1).
2. Attribute each offer by `accountid_other` → SteamID64.
3. Reconcile state per research R4.
4. On `Accepted` with sufficient keys: insert the `grant` ledger row and set the payment `complete`
   **in one transaction**, relying on `UNIQUE (method, provider_ref)` for exactly-once (research R7).
5. Rate limiting or transport failure: log, leave all payment state untouched, exit non-zero.

**Never**: marks a payment failed because Steam was unreachable; credits a payment twice; credits one
not in `Accepted`.

### `flask reconcile-servers`

Advances server state against the clock: `scheduled → starting → running` at `window_starts_at`,
`running → in_grace` at `window_ends_at`, `in_grace → stopped` after `GRACE_MINUTES` with
`stopped_reason = time_expired`. Spends reserved credits as a window begins; returns them for
`cancelled` or `failed` (FR-067).

Idempotent — safe to run repeatedly and after a missed interval.

---

## Route summary

| Method | Path | Status |
|---|---|---|
| GET | `/servers` | changed |
| GET | `/servers/<id>` | changed |
| POST | `/servers/<id>/settings` | unchanged contract |
| POST | `/servers/<id>/console` | changed (refuses when not running) |
| ~~GET/POST~~ | ~~`/servers/new`~~ | **removed** |
| POST | `/servers/<id>/extend` | new |
| POST | `/scrims/<id>/server/attach` | new |
| GET | `/credits` | new |
| POST | `/credits/trade/start` | new |
| POST | `/credits/cancel/<payment_id>` | new |
| POST | `/account/trade-link` | new |
| POST | `/account/trade-link/delete` | new |
| POST | `/scrims/propose` | `use_credits` added |
| POST | `/scrims/listings/new` | `use_credits` added |
| POST | `/scrims/<id>/claim` | `use_credits` added |
| GET | `/scrims/<id>` | server state + extend added |
