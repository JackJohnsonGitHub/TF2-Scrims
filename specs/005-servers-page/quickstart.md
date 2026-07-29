# Quickstart: Validating the Servers Page

**Feature**: `005-servers-page` · **Plan**: [plan.md](./plan.md) · **Contracts**:
[servers-routes.md](./contracts/servers-routes.md)

How to prove this feature works end to end. Entity fields are in
[data-model.md](./data-model.md) and route shapes in the contracts — not repeated here.

---

## Prerequisites

```bash
cd ~/Projects/TF2-Server-Hosting
uv venv .venv && uv pip install --python .venv/bin/python3 -r requirements.txt

export APP_SECRET_KEY="$(.venv/bin/python3 -c 'import secrets;print(secrets.token_hex(32))')"
export APP_BASE_URL="http://localhost:5000"
export DB_PATH="./app.db"
```

**Note on the venv**: its scripts hardcode an absolute interpreter path, so a moved project leaves
`.venv/bin/pytest` failing with a confusing "required file not found". Recreate it, or invoke through
`.venv/bin/python3 -m pytest`.

Payment configuration — real values from the secret store, placeholders for local work:

```bash
export STEAM_API_KEY="<from OpenBao>"        # now load-bearing, not optional
export OPERATOR_TRADE_URL="<from OpenBao>"   # contains a token; treat as secret
```

## Automated validation

```bash
.venv/bin/python3 -m pytest -q                          # full suite
.venv/bin/python3 -m pytest tests/unit/test_credits.py -q
.venv/bin/python3 -m pytest tests/integration/test_credits_flow.py -q
```

**Baseline**: 226 tests pass as of `c58b403`. This feature adds tests and deliberately replaces
`test_create_server_form_renders` (see plan, Constitution Check note 1).

No test may require network access or a real API key — Steam is mocked at the `app/steam_trade.py`
seam, as RGL and Steam OpenID already are.

---

## Scenario 1 — A free account sees the free product (US1, FR-031, FR-012)

```bash
.venv/bin/python3 scripts/seed_demo_team.py
.venv/bin/flask --app app run --debug
```

Sign in with Steam, link RGL, open `/servers`.

**Expect**: balance of 0 credits · the price stated (2 keys → 5 credits; 1 credit = 1 hour; extend
= 1 credit per 30 min) · an empty state saying scheduling is free · **no credit-spending action
anywhere** · no `+ Create server` in the nav or on the dashboard.

**Fails if**: any spend action renders at zero balance (FR-065), or `/servers/new` still resolves.

## Scenario 2 — Trade link is a precondition (FR-044–FR-047, research R2)

From `/servers`, start the payment action with no trade link on file.

**Expect**: redirected to `/account`, told the link is needed for the escrow pre-check and item
return. Save a malformed link → rejected per-field, nothing stored. Save someone else's link →
rejected, because its `partner` does not resolve to your SteamID64.

**Why this matters**: `GetTradeHoldDurations` requires `trade_offer_access_token`, which only exists
inside the user's own trade URL. Without it the pre-check cannot run at all.

## Scenario 3 — Escrow blocks payment (FR-041, FR-042, SC-013)

Mock `steam_trade.get_trade_hold_duration` to return `their_seconds > 0`.

**Expect**: the Trade action is refused with a plain explanation of Steam Guard Mobile. **No trade is
started.** Then mock `SteamUnavailable`: payment is still refused — the pre-check fails **closed**,
because guessing wrong means taking money for a server that cannot be delivered in time.

## Scenario 4 — Payment to credits (US5, FR-036–FR-039, FR-049, FR-050)

With no hold, start the payment: a `payments` row appears in `started` and the browser is sent to
Steam. Then drive the poller with mocked offers:

```bash
.venv/bin/flask --app app poll-payments
```

| Mocked offer | Expect |
|---|---|
| state 2 (Active), 2 keys | stays `started`; no credits |
| state 11 (InEscrow) | `held`; **no credits** (FR-040) |
| state 3 (Accepted), 2 keys | `complete`; **+5 credits**; a `grant` ledger row |
| state 3, 4 keys | **+10 credits** (`floor(4 × 2.5)`) |
| state 3, 1 key | `insufficient`; received-vs-needed stated; no credits |
| state 3, 20 hats | `insufficient`, not `failed`; non-matching items count zero |
| state 3, keys from another `appid` | `insufficient` — appid scoping (FR-049) |
| state 7 (Declined) | `failed` with reason |

**Run the poller twice on the same accepted offer.** Credits MUST NOT double. That is the
`UNIQUE (method, provider_ref)` constraint, not poller politeness — verify by asserting the balance
after the second run.

**Then make Steam unreachable and run again**: every payment state unchanged, nothing marked
`failed`, non-zero exit (SC-014).

**The trap to test explicitly**: a poller passing only `active_only=1` never observes `Accepted`,
because it is terminal and excluded. Assert the historical pass happens, or this whole scenario
silently passes while paying nobody.

## Scenario 5 — Spend credits while scheduling (US2, FR-052–FR-058)

With 5 credits, propose a scrim and tick the server option.

**Expect**: scrim created · 1 credit reserved · server in `scheduled` · window starting at the
scrim's **scheduled time** (FR-078). Repeat for posting a listing and for **claiming** one.

Now the Principle I checks — each must leave the scrim created:

| Condition | Expect |
|---|---|
| Zero balance, option not rendered | scrim still created |
| Zero balance, `use_credits` posted anyway | scrim created, field ignored, no server |
| Steam unreachable | scrim created |
| `STEAM_API_KEY` unset | scrim created |
| Reservation fails | scrim created, serverless — a valid state, not an error (FR-055) |

**Fails if** any of these blocks, delays, or rolls back scheduling. This is the constitution's first
principle and the most important thing in the feature.

## Scenario 6 — Runtime, grace, extension (US5, FR-062–FR-077)

```bash
.venv/bin/flask --app app reconcile-servers
```

Move the clock (or seed windows relative to now) and reconcile at each boundary:

| Clock | State | Credits |
|---|---|---|
| before `window_starts_at` | `scheduled` | 1 reserved |
| at `window_starts_at` | `starting` → `running` | reserved → spent |
| at `window_ends_at` | `in_grace`, prominent warning | nothing further (FR-073) |
| +15 min, un-extended | `stopped`, `stopped_reason = time_expired` | spent |

Then extend from `/servers/<id>` **and** from the scrim's own page (FR-080):

**Expect**: +30 minutes · balance −1 · cost and added time shown before committing (FR-081) ·
players never interrupted (FR-077) · **no Steam call in the path** — that is what makes SC-010's
15-second budget achievable.

Extend a second time after the grace was used → allowed while credits remain, but **no second
grace** (FR-074). At zero balance the extend action is absent, and posting to it anyway is still
refused server-side.

**Run the reconciler twice at every boundary.** Idempotent — no double spend.

## Scenario 7 — Access control (FR-001, FR-002, SC-003, SC-009)

**Expect**: another team's server absent from `/servers` and **404** — not 403 — by direct id. A
team member who is not the owner can see and join but not change settings or extend (FR-027).

```bash
# The administrative password must appear nowhere in any response
curl -s http://localhost:5000/servers/1 | grep -i rcon    # expect no password
```

## Scenario 8 — Ledger explains everything (SC-011, FR-068)

Open `/credits`.

**Expect**: every grant, reserve, release, spend and extension listed with its cause and what it
relates to. Sum of deltas equals the displayed available balance — necessarily, since the balance is
derived from these rows rather than cached alongside them.

---

## Deployment check

```bash
docker build -t harbor.irulast.com/tf2-hosting/app:dev .
docker run --rm -p 8000:8000 -e APP_SECRET_KEY=dev -e APP_BASE_URL=http://localhost:8000 \
  harbor.irulast.com/tf2-hosting/app:dev
curl -fsS http://127.0.0.1:8000/healthz    # -> ok

kubectl apply -f deploy/cronjob-poll-payments.yaml -f deploy/cronjob-reconcile-servers.yaml
```

Use `localhost`, not `127.0.0.1`, when exercising sign-in — `APP_BASE_URL` is what Steam returns to,
and the §11.1 check now requires the returned `return_to` to match it exactly.

**Verify in-cluster**: exactly one poller instance runs at a time. Two concurrent pollers racing on
the same trade is the failure the CronJob design exists to prevent; the `UNIQUE` constraint is the
backstop, and both should hold.

## Done when

- [ ] Full suite green (226 + new, less the one deliberately replaced test)
- [ ] Scenarios 1–8 pass by hand
- [ ] Double-poll and double-reconcile change no balance
- [ ] Scheduling succeeds with zero credits, no API key, and Steam unreachable
- [ ] `/servers/new` gone from routes, templates, nav, and dashboard
- [ ] No secret appears in any response, log line, or committed file
