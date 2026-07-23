# Phase 1 Data Model: Scrims Dashboard, Team Rosters & Attendance

Extends the 003 store. **Five new tables, zero changes to existing table shapes** (new tables are
picked up by `db.py`'s idempotent `CREATE TABLE IF NOT EXISTS` startup schema — no migrations).
All timestamps ISO-8601 UTC strings (003 convention; lexicographic compare == chronological).
Tables: `rgl_rosters`, `rgl_roster_meta`, `scrim_attendance` (US1–US3), plus `rgl_seasons` and
`rgl_season_teams` (US4 division browser).

## Table: `rgl_rosters` (cached current roster per team)

| Field | Type | Description |
|---|---|---|
| `rgl_team_id` | INTEGER, FK → `rgl_teams.rgl_team_id` | Team the row belongs to. |
| `steam_id` | TEXT | Player's SteamID64 (from RGL `players[].steamId`). |
| `name` | TEXT | Player name as known to the league. |
| `is_leader` | INTEGER (0/1) | RGL leader flag (rendered as a badge). |
| PRIMARY KEY | (`rgl_team_id`, `steam_id`) | |

Holds **current** players only (RGL entries with `leftAt == null`). Rebuilt atomically per team on
each successful fetch (`DELETE` team's rows + `INSERT` fresh, one transaction). Never mutated on
failure — a fetch error leaves the last good roster in place (stale-if-error, research §2).

## Table: `rgl_roster_meta` (per-team fetch stamp)

| Field | Type | Description |
|---|---|---|
| `rgl_team_id` | INTEGER PK, FK → `rgl_teams.rgl_team_id` | One row per fetched team. |
| `fetched_at` | TEXT | Last **successful** roster fetch. Drives the ~1 h TTL. |

Separate from `rgl_rosters` so a legitimately empty roster doesn't look like "never fetched", and
from `rgl_teams` so no ALTER of an existing table is needed.

## Table: `scrim_attendance` (who's showing up, per listing)

| Field | Type | Description |
|---|---|---|
| `scrim_id` | INTEGER, FK → `scrims.id` | The listing (origin = `listing` only, enforced in code). |
| `player_steam_id` | TEXT | Roster player being marked (SteamID64 — same identity space as `users`). |
| `player_name` | TEXT | Name snapshot at marking time — keeps departed players renderable + flagged. |
| `status` | TEXT | `attending` \| `not_attending` \| `unconfirmed`. No row at all also reads as unconfirmed. |
| `marked_by` | TEXT, FK → `users.steam_id` | Who last set it (self, or the listing creator). |
| `updated_at` | TEXT | Last change. |
| PRIMARY KEY | (`scrim_id`, `player_steam_id`) | Upsert target. |

### Authorization / invariants (server-side, `attendance.py`)

- Scrim MUST exist, have `origin = 'listing'`, and not be `declined` (proposals never get trackers).
- Actor MUST be a member of the scrim's **proposer team** (`rgl_memberships` check, 003's FR-016
  pattern) — others get 403 on write and see no attendance on read (FR-016).
- Actor may write `player_steam_id == actor` (self), **or** anything if
  `actor == scrims.created_by` (creator override, clarification #4); otherwise 403 (FR-014).
- Writes rejected once `scheduled_at <= now` — tracker becomes read-only (FR-017) — and after
  `cancelled` status.
- `status` MUST be one of the three values; tally = count of `attending` vs
  `FORMAT_SIZES[format]` (sixes 6, prolander 7, highlander 9 — FR-015).

## Table: `rgl_seasons` (US4 — season directory header)

| Field | Type | Description |
|---|---|---|
| `season_id` | INTEGER PK | RGL season id (comes from the proposing team's stored `season_id`). |
| `name` | TEXT | e.g. "6s Season 20". |
| `format` | TEXT | Derived from the season's `formatName` → `sixes` \| `highlander` \| `prolander`. |
| `division_sorting` | TEXT (JSON) | RGL's `divisionSorting` map (division id → sort rank) verbatim; orders division groups. |
| `fetched_at` | TEXT | Last successful season fetch; drives `RGL_DIRECTORY_TTL_SECONDS` (default 24 h). |

## Table: `rgl_season_teams` (US4 — participation + hydration state)

| Field | Type | Description |
|---|---|---|
| `season_id` | INTEGER, FK → `rgl_seasons.season_id` | |
| `rgl_team_id` | INTEGER | From the season's `participatingTeams`. |
| `division_id` | INTEGER, nullable | Filled at hydration (team endpoint's `divisionId`); groups the browser. |
| `hydrated_at` | TEXT, nullable | NULL = pending hydration (name/tag/division unknown so far). |
| PRIMARY KEY | (`season_id`, `rgl_team_id`) | |

Hydration (research §8): each browse request hydrates ≤ `RGL_HYDRATE_BATCH` pending rows via the
team endpoint, **upserting the team into `rgl_teams`** (shared identity store — name, tag, format,
division_name, season_id) and stamping this row. Failed hydrations leave rows pending (retried on
a later request); the browser renders hydrated teams only, with an "X of Y teams loaded" note
while any are pending. Off-platform labeling = no `rgl_memberships` row for the team.

### New/changed queries (US4)

| Query | Behavior | Requirement |
|---|---|---|
| NEW `platform_teams(format)` | same-format teams with ≥ 1 membership row — replaces `all_teams()` as the propose form's quick pick (research §9) | FR-021 |
| NEW `ensure_season(season_id)` | fetch/refresh season header + participation within TTL; stale-if-error | FR-018, FR-021 |
| NEW `hydrate_season_teams(season_id, batch)` | hydrate up to `batch` pending teams; bounded per request | FR-018, FR-019 |
| NEW `division_browser(season_id, division_id?)` | hydrated divisions (ordered by `division_sorting`) and, for a chosen division, its teams with on-platform flags | FR-018, FR-019 |

Proposal creation itself is **unchanged** (003 state machine): an off-platform opponent works
because hydration put its row in `rgl_teams`, satisfying the FK and the same-format check; no
membership rows exist for it, so nobody can accept until a member joins and links (FR-020).

## Changed queries (existing `scrims` table — no shape change)

| Query | Change | Requirement |
|---|---|---|
| `open_listings(fmt)` | add `AND s.scheduled_at > :now` | FR-003, SC-002 |
| `my_open_listings(steam_id)` | add `AND s.scheduled_at > :now` (own expired listings leave the dashboard too) | FR-003 |
| `claim(...)` atomic UPDATE | `WHERE id = ? AND status = 'open'` → `... AND scheduled_at > :now` (expired = unclaimable even mid-race) | FR-003, edge case "expires while viewed" |
| NEW `get_scrim_for_viewer(id, steam_id)` | detail visibility: open **future** listing → any RGL-linked user; else members of either team only; proposal-origin → participants only (research §6) | FR-009, FR-016 |

State machine, statuses, and all other 003 transitions are **unchanged** — expiry is a read-side
filter, not a status.

## Relationships

- `rgl_teams (1) ── (0..n) rgl_rosters` — cached players; `(1) ── (0..1) rgl_roster_meta`.
- `scrims (1) ── (0..n) scrim_attendance`, rows keyed to roster players by SteamID64.
- `scrim_attendance.player_steam_id` intentionally has **no** FK to `rgl_rosters` — attendance
  must survive roster rebuilds and departed players (rendered with a "no longer on team" flag when
  absent from the current roster).
- `rgl_seasons (1) ── (0..n) rgl_season_teams`; hydrated rows correspond to `rgl_teams` entries
  (shared identity store) — `rgl_teams` now holds league-wide teams, not only linked users' teams,
  which is why the quick pick scopes to membership-backed teams (research §9).
