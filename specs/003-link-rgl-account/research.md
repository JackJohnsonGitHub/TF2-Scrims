# Phase 0 Research: Link RGL Account & Schedule Scrims

All Technical Context items were resolvable from the spec, the constitution, and the (verified) RGL
public API. No open `NEEDS CLARIFICATION` markers remain.

## Decision 1 — RGL data source: public API, keyed by SteamID, no key

- **Decision**: Fetch `https://api.rgl.gg/v0/profile/{steamid64}` with `requests`. It returns
  `name`, `avatar`, `status` (`isVerified`/`isBanned`/`isOnProbation`), and `currentTeams` keyed by
  format (`sixes`, `highlander`, `prolander`), each with `id`, `tag`, `name`, `seasonId`,
  `divisionName` (or `null` when the user has no team in that format). **No API key required.**
- **Rationale**: This single endpoint gives everything US1 needs, keyed by the SteamID we already have
  verified from sign-in — so linking is auto-detected with zero manual entry (FR-002). Verified live
  against a real profile during specify/clarify.
- **Alternatives considered**: scraping rgl.gg HTML profile pages (brittle); a separate
  `/v0/profile/{id}/teams` call (unnecessary — the profile payload already carries `currentTeams`).

## Decision 2 — Failure handling for the external RGL dependency

- **Decision**: All RGL calls use a short timeout. Map outcomes explicitly: `404`/empty → **no RGL
  profile**; profile with all-`null` `currentTeams` → **linked, no current team**; timeout/5xx/network
  → **unavailable** (retry message). Never surface a stack trace or break the page (FR-006, SC-008).
- **Rationale**: Principle VII — an external dependency must not take the page down. These three states
  drive the link UI and the scheduling gate.
- **Alternatives considered**: caching aggressively to mask outages (adds staleness/complexity; a
  last-refreshed indicator + on-demand refresh is enough now).

## Decision 3 — Teams as first-class rows; membership drives authority

- **Decision**: Store each current team as a row in `rgl_teams` keyed by RGL's **global team id**, and
  record `rgl_memberships(steam_id, rgl_team_id)` when a user links. A user may act for a team only if
  a membership row exists (FR-016). Directed proposals target an existing platform team; acceptance is
  allowed for any member of the opponent team.
- **Rationale**: Scrims are team-vs-team, so both sides must reference the same stable team identity —
  RGL's team id is global and shared across the two teams' members. Membership rows are what let the
  opponent's captain see/accept a proposal and enforce "act only for your team".
- **Alternatives considered**: embedding team data on the user row only (can't share a team between two
  users/teams, breaks acceptance); trusting a claimed team id from the client (violates FR-016).

## Decision 4 — One Scrim entity with a state machine covering both paths

- **Decision**: Model both scheduling paths as one `scrims` row with `origin` (`proposal` | `listing`)
  and a `status`:
  - **Directed proposal**: created `pending` with `proposer_team_id` + `opponent_team_id`.
    `accept → confirmed`, `decline → declined`, proposer `withdraw → cancelled`.
  - **Open listing**: created `open` with `opponent_team_id = NULL`. Another same-format team
    `claim → confirmed` (sets `opponent_team_id`); owner `cancel → cancelled`.
  - Either side may `cancel` a `confirmed` scrim → `cancelled` (kept, not deleted — FR-015).
- **Rationale**: One entity + explicit transitions keeps the two paths consistent and the rules
  testable in isolation (`scrims.py`). Statuses map directly to the spec.
- **Alternatives considered**: separate `proposals` and `listings` tables (duplicates the confirmed-
  match concept and the queries); deleting on decline/cancel (loses the audit trail FR-015 wants).

## Decision 5 — Guards & validation

- **Decision**: Reuse `login_required` (002) for all routes; add a small `rgl_link_required` guard
  that redirects/blocks users without a linked RGL team (FR-008). Server-side validation enforces:
  same-format only (FR-012), no self-scrim, no past date/time, claim only an `open` listing, and
  first-claim-wins via a conditional update (FR-011/FR-017). Every action re-checks membership
  server-side (FR-016) — never trust a team id from the form.
- **Rationale**: Centralizes the gate; keeps correctness/authority server-side per Principle IV.
- **Alternatives considered**: client-side format filtering only (insufficient — must enforce on the
  server); row locking (SQLite's atomic `UPDATE ... WHERE status='open'` is enough for first-claim).

## Decision 6 — Date/time handling

- **Decision**: Store scrim `scheduled_at` as an ISO-8601 UTC timestamp; accept input in the user's
  local time and convert; display in local time with the zone shown.
- **Rationale**: Unambiguous storage, correct comparisons for "past date/time" rejection and
  upcoming/pending sorting.
- **Alternatives considered**: storing naive local strings (ambiguous, breaks comparisons).

## Decision 7 — Persistence approach (continue stdlib sqlite3, note the ceiling)

- **Decision**: Extend the 002 stdlib-`sqlite3` store with the four new tables and per-concern
  data-access modules (`rgl_store.py`, `scrims.py`). Keep `CREATE TABLE IF NOT EXISTS` idempotent init.
- **Rationale**: No new dependency; consistent with 002; fine at this scale. The scrim queries (joins
  across teams/memberships, state filters) are the most complex so far but still straightforward SQL.
- **Alternatives considered**: adopt SQLAlchemy now (heavier; still not required). **Noted ceiling**:
  once relationships/queries grow further (e.g., server-linked scrims, history), migrating to an ORM
  or Postgres becomes worthwhile — flagged for a future feature, not this one.
