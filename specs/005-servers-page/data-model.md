# Phase 1 Data Model: The Servers Page

**Feature**: `005-servers-page` · **Date**: 2026-07-29 · **Spec**: [spec.md](./spec.md) ·
**Research**: [research.md](./research.md)

Additive only. Every table below is a new `CREATE TABLE IF NOT EXISTS` appended to
`app/db.py:SCHEMA`, so `init_schema` stays idempotent and no `ALTER TABLE` migration path is needed
for already-deployed databases. Existing tables (`users`, `rgl_links`, `rgl_teams`,
`rgl_memberships`, `scrims`, `scrim_attendance`, `rgl_rosters`, `rgl_roster_meta`) are unchanged.

Timestamps are ISO-8601 UTC strings, matching the existing convention.

---

## Prerequisite: connection pragmas

Not a table, but required before any of this is safe (research R6). Applied in `get_db()` and in the
CLI commands' own connections:

```
PRAGMA journal_mode = WAL;     -- readers don't block on the poller's writes
PRAGMA busy_timeout = 5000;    -- wait rather than fail instantly on contention
PRAGMA foreign_keys = ON;      -- currently OFF, making existing REFERENCES decorative
```

---

## `steam_trade_links`

A user's own trade URL. Separate table rather than a column on `users` so no migration is needed.

| Column | Type | Notes |
|---|---|---|
| `steam_id` | TEXT PK → `users` | One link per account. |
| `trade_url` | TEXT NOT NULL | The full URL as entered. |
| `partner_id` | TEXT NOT NULL | 32-bit account id parsed from `?partner=`. |
| `access_token` | TEXT NOT NULL | Token parsed from `&token=`. **Required for the escrow pre-check.** |
| `updated_at` | TEXT NOT NULL | |

**Validation** (FR-046): must parse to both a `partner` and a `token`; `partner` must convert to the
same SteamID64 as the signed-in account — a link belonging to somebody else is rejected, since it
would make the pre-check answer about the wrong person.

**Derivation**: `steamid64 = partner_id + 76561197960265728`.

**Visibility** (FR-047): the owning user and the operator only.

---

## `payments`

One attempt to pay, by any method. For the trade method, one Steam trade offer.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `steam_id` | TEXT NOT NULL → `users` | Who is paying. |
| `method` | TEXT NOT NULL | `steam_trade` today; the column is what keeps FR-048 honest. |
| `provider_ref` | TEXT | `tradeofferid`. NULL until the offer is observed. |
| `state` | TEXT NOT NULL | See state machine below. |
| `state_reason` | TEXT | Why it is insufficient or failed — shown to the payer (FR-039, FR-043). |
| `items_expected` | INTEGER NOT NULL | Keys required at the time of the attempt. |
| `items_received` | INTEGER | Keys actually seen (FR-050). |
| `credits_granted` | INTEGER | Credits produced on completion. |
| `hold_until` | TEXT | Escrow expiry when known; NULL when held with unknown expiry (research R2). |
| `target_scrim_id` | INTEGER → `scrims` | The scrim this payment was started for, if any (FR-054). |
| `created_at` / `updated_at` | TEXT NOT NULL | |

**Constraints**:
- `UNIQUE (method, provider_ref)` — the whole double-credit defence (research R7). Enforced by the
  store, not by poller discipline.
- Partial-unique intent: at most one `started` payment per user per method. Enforced in the service
  layer, since SQLite partial indexes on a mutable state column are awkward.

### Payment state machine

```
                    ┌───────────────► insufficient ──┐
                    │                                 │  (payer told what
started ────────────┼───────────────► failed ─────────┤   arrived vs needed)
   │                │                                 │
   │                └───────────────► held ───────────┤
   │                                    │             │
   └────────────────────────────────────┴──► complete ─┴──► credits granted
```

| State | Meaning | Provider states (research R4) |
|---|---|---|
| `started` | Trade opened, not yet resolved | 2 Active, 9 CreatedNeedsConfirmation |
| `held` | In Steam escrow; no credits yet (FR-040) | 11 InEscrow |
| `complete` | Accepted; credits granted (FR-038) | 3 Accepted |
| `insufficient` | Wrong or too few items (FR-039) | 3 Accepted but contents fail the rule |
| `failed` | Cancelled, declined, expired, invalid (FR-043) | 1, 4, 5, 6, 7, 8, 10 |

`started` and `held` MUST NOT be reachable from `complete`. Steam being unreachable MUST NOT move a
payment to `failed` (SC-014).

---

## `credit_ledger`

Append-only. **The source of truth for every balance** (research R8). Rows are never updated or
deleted.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `steam_id` | TEXT NOT NULL → `users` | Whose balance (FR-070: account-level). |
| `delta` | INTEGER NOT NULL | Signed. Positive grants, negative spends. |
| `kind` | TEXT NOT NULL | `grant`, `reserve`, `release`, `spend`, `extend`. |
| `cause` | TEXT NOT NULL | Human-readable, shown in the ledger UI (FR-068). |
| `payment_id` | INTEGER → `payments` | Set for `grant`. |
| `scrim_id` | INTEGER → `scrims` | Set for `reserve` / `release`. |
| `server_id` | INTEGER → `servers` | Set for `spend` / `extend`. |
| `created_at` | TEXT NOT NULL | |

**Derived balances** — no cached column exists:

```
granted   = SUM(delta) WHERE kind = 'grant'
reserved  = -SUM(delta) WHERE kind = 'reserve'  -  (releases)
available = SUM(delta) over all rows
```

`available` is simply `SUM(delta)`, because `reserve` and `spend` are recorded as negatives and
`release` as a positive. This is what FR-065 gates every credit-spending action on, and what SC-011
requires be explainable from these rows alone.

**Invariant**: `available` MUST NEVER go negative. Enforced by checking inside the same transaction
as the insert.

---

## `servers`

Replaces the module-level `SAMPLE_SERVERS` list in `app/models.py` (research R10). State is real;
the compute behind it is simulated this increment.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `scrim_id` | INTEGER → `scrims` | Set for a per-scrim server (FR-010). NULL for a season-term server. |
| `owner_steam_id` | TEXT NOT NULL → `users` | The captain who paid (FR-027, Principle VIII). |
| `team_id` | INTEGER → `rgl_teams` | Who may see and join it (FR-001). |
| `state` | TEXT NOT NULL | See below. |
| `name` | TEXT NOT NULL | |
| `map` | TEXT NOT NULL | |
| `max_slots` | INTEGER NOT NULL | |
| `join_password` | TEXT | Optional (FR-008). |
| `address` | TEXT | Simulated this increment. |
| `players` | INTEGER | Simulated; NULL means unknown (FR-007). |
| `window_starts_at` | TEXT | The scrim's scheduled time (FR-078). |
| `window_ends_at` | TEXT | Absolute boundary; extensions push it out (research R9). |
| `grace_used` | INTEGER NOT NULL DEFAULT 0 | Once per server (FR-074). |
| `demo` | INTEGER NOT NULL DEFAULT 0 | Keeps the sample-data label (FR-013). |
| `stopped_reason` | TEXT | `time_expired`, `cancelled`, `failed_to_place` — so FR-076 can say *why*. |
| `created_at` / `updated_at` | TEXT NOT NULL | |

**Never stored here**: the RCON/administrative password (FR-009, FR-035, SC-009). It belongs in the
secret store, keyed by server, and is never selected into a template context.

### Server lifecycle

```
 pending_payment ──► scheduled ──► starting ──► running ──► in_grace ──► stopped
        │                │                         │            │
        │                └──► cancelled            └────────────┴──► (extend → running)
        └──► cancelled                             └──► failed
```

| State | Meaning | Credits |
|---|---|---|
| `pending_payment` | Option chosen, payment not complete (FR-055) | none reserved |
| `scheduled` | Credits reserved, window in the future | 1 reserved |
| `starting` | Provisioning (simulated) | reserved |
| `running` | Inside its window (FR-062) | spent as the window begins |
| `in_grace` | Past `window_ends_at`, inside the 15-min grace (FR-072) | nothing further charged (FR-073) |
| `stopped` | Window and grace elapsed, un-extended (FR-076) | spent |
| `cancelled` | Scrim cancelled before start (FR-057) | **released** |
| `failed` | Could not be placed (FR-029, FR-030) | **released** (FR-067, Principle VII) |
| `unknown` | Live state indeterminable (FR-007) | unchanged |

`in_grace` is enterable only once per server. `stopped` and `cancelled` are terminal.

---

## Relationships

```
users ─1──1─ steam_trade_links
  │
  ├─1──*─ payments ──1──*─ credit_ledger (kind='grant')
  │
  ├─1──*─ credit_ledger
  │
  └─1──*─ servers (as owner)
                │
                ├──*──1─ scrims        (per-scrim servers; NULL for season-term)
                └──*──1─ rgl_teams     (who may see and join)

scrims ─1──0..1─ servers               (FR-058: one server per scrim)
```

---

## Requirements coverage

| Area | Requirements | Where |
|---|---|---|
| Free by default | FR-031 | absence of `credit_ledger` rows; no tier column needed |
| Trade link | FR-044–FR-047 | `steam_trade_links` |
| Payment observation | FR-036–FR-043, FR-049, FR-050 | `payments` |
| Credits & ledger | FR-059–FR-061, FR-067–FR-070 | `credit_ledger` |
| Runtime & extension | FR-062–FR-064, FR-072–FR-079 | `servers.window_*`, `grace_used` |
| Access control | FR-001, FR-002 | `servers.owner_steam_id` + `team_id`, reusing `can_access` |
| Attach while scheduling | FR-052–FR-058 | `servers.scrim_id`, `payments.target_scrim_id` |
| Failure visibility | FR-029, FR-030, FR-076 | `servers.state`, `stopped_reason` |

**Deliberately not modelled**: an account "tier". Free is the absence of credits (FR-031), so a tier
column would be a second, drift-prone truth for something already derivable.

**Deferred to feature 006**: season-term purchase (constitution v3.1.0 leaves its unit undefined), so
`servers.scrim_id = NULL` is representable but has no way to be created yet.
