# Phase 1 Data Model: Link RGL Account & Schedule Scrims

Extends the 002 SQLite store. Four new tables. All timestamps ISO-8601 UTC.

## Table: `rgl_links` (one row per linked account)

| Field | Type | Description |
|---|---|---|
| `steam_id` | TEXT PK, FK → `users.steam_id` | The account (one RGL profile per account). |
| `profile_name` | TEXT | RGL persona name at last refresh. |
| `state` | TEXT | `linked` \| `no_profile` \| `no_team` (last known link outcome). |
| `is_verified` | INTEGER (0/1) | RGL status flag (informational badge). |
| `is_banned` | INTEGER (0/1) | RGL status flag. |
| `is_on_probation` | INTEGER (0/1) | RGL status flag. |
| `linked_at` | TEXT | First link time. |
| `last_refreshed_at` | TEXT | Last successful RGL fetch. |

Unlink deletes the row (and the user's `rgl_memberships`; `rgl_teams` rows are shared and kept).

## Table: `rgl_teams` (first-class team identity, shared)

| Field | Type | Description |
|---|---|---|
| `rgl_team_id` | INTEGER PK | RGL's **global** team id (shared across members/opponents). |
| `name` | TEXT | Team name. |
| `tag` | TEXT | Team tag. |
| `format` | TEXT | `sixes` \| `highlander` \| `prolander`. |
| `division_name` | TEXT | e.g. "RGL-Amateur". |
| `season_id` | INTEGER | RGL season id. |
| `updated_at` | TEXT | Last time these details were refreshed. |

Upserted on link/refresh from `currentTeams`. `format` governs scrim matching (FR-012).

## Table: `rgl_memberships` (which users may act for which team)

| Field | Type | Description |
|---|---|---|
| `steam_id` | TEXT, FK → `users` | Member. |
| `rgl_team_id` | INTEGER, FK → `rgl_teams` | Team they are currently on. |
| PRIMARY KEY | (`steam_id`, `rgl_team_id`) | |

Rebuilt from RGL on each link/refresh (rows removed if the user left the team). Authority check
(FR-016): a user may act for a team **iff** a membership row exists.

## Table: `scrims` (match — both scheduling paths)

| Field | Type | Description |
|---|---|---|
| `id` | INTEGER PK | |
| `format` | TEXT | Must equal both teams' format. |
| `scheduled_at` | TEXT (UTC) | Proposed/agreed match time. |
| `origin` | TEXT | `proposal` \| `listing`. |
| `proposer_team_id` | INTEGER FK → `rgl_teams` | The creating team. |
| `opponent_team_id` | INTEGER FK → `rgl_teams`, nullable | Set at creation (proposal) or on claim (listing). |
| `status` | TEXT | `pending` \| `open` \| `confirmed` \| `declined` \| `cancelled`. |
| `created_by` | TEXT FK → `users` | The acting user. |
| `created_at` / `updated_at` | TEXT | Audit timestamps. |
| `notes` | TEXT, nullable | Optional free text. |

### State machine

```
proposal:  (create) → pending ──accept──▶ confirmed ──cancel(either)──▶ cancelled
                         ├──decline──▶ declined
                         └──withdraw─▶ cancelled

listing:   (create) → open ──claim(same-format team)──▶ confirmed ──cancel(either)──▶ cancelled
                        └──cancel(owner)──▶ cancelled
```

### Validation / invariants (server-side)

- Actor must be RGL-linked with a team, and a **member** of the team they act for (FR-008, FR-016).
- `format` of proposer and opponent teams MUST match (FR-012).
- `opponent_team_id` MUST differ from `proposer_team_id` (no self-scrim) (FR-017).
- `scheduled_at` MUST be in the future at creation (FR-017).
- **Claim** succeeds only via an atomic `UPDATE ... WHERE id=? AND status='open'` — first claim wins;
  a second claim finds no `open` row and is told it's taken (FR-011).
- Accept/decline allowed only from `pending`; claim only from `open`; cancel from `pending`/`open`/
  `confirmed`. Terminal states (`declined`/`cancelled`) are immutable.
- No side effects on servers/payment on any transition (FR-018).

## Relationships

- `users (1) ── (0..1) rgl_links` — one RGL link per account.
- `users (M) ── (N) rgl_teams` via `rgl_memberships`.
- `scrims.proposer_team_id` / `opponent_team_id` → `rgl_teams`. A confirmed scrim references two teams
  of the same `format`.
