# Phase 1 Contract: Scrim Scheduling Routes

Server-rendered; all routes `@login_required` **and** `rgl_link_required` (must be RGL-linked with a
team — FR-008). Every action re-checks team membership server-side (FR-016).

## Routes

| Method | Path | Purpose | Maps to |
|---|---|---|---|
| GET | `/scrims` | My scrims: incoming + outgoing pending proposals, upcoming confirmed matches, my open listings — across my teams. | FR-014 |
| GET | `/scrims/new` | Propose form: choose one of my teams, an opponent team (same format), a future date/time. | FR-009, FR-010 |
| POST | `/scrims/propose` | Create a directed proposal (`pending`). Validates membership, same-format, not-self, future time. | FR-010, FR-012, FR-016, FR-017 |
| POST | `/scrims/<id>/accept` | Opponent-member accepts a `pending` proposal → `confirmed`. | FR-010 |
| POST | `/scrims/<id>/decline` | Opponent-member declines → `declined`. | FR-010 |
| POST | `/scrims/<id>/withdraw` | Proposer-member withdraws a `pending` proposal → `cancelled`. | FR-010 |
| POST | `/scrims/<id>/cancel` | Either team cancels a `confirmed` scrim → `cancelled` (kept). | FR-015 |
| GET | `/scrims/listings` | Browse open listings, filterable by format. | FR-011, FR-014 |
| POST | `/scrims/listings/new` | Create an open listing (my team, format, future time) → `open`. | FR-011 |
| POST | `/scrims/listings/<id>/claim` | Claim an `open` listing with one of my same-format teams → `confirmed` (atomic first-wins). | FR-011, FR-012, FR-017 |
| POST | `/scrims/listings/<id>/cancel` | Owner cancels an unclaimed listing → `cancelled`. | FR-011 |

## Behavior contract

- **Gate (FR-008)**: a user with no linked RGL team is redirected/blocked with "link RGL / join a team
  first" on any scheduling route.
- **Team selection (FR-009)**: the acting team is chosen from the user's own teams; the server verifies
  membership on every action (never trusts a posted team id — FR-016).
- **Same-format only (FR-012)**: opponent/claiming team `format` must equal the scrim `format`; the
  propose form and listings browse only offer same-format options, and the server re-validates.
- **Directed flow (FR-010)**: `propose` → `pending`; accept→`confirmed`, decline→`declined`,
  withdraw→`cancelled`. Accept/decline allowed only to a **member of the opponent team**; withdraw only
  to a member of the proposer team.
- **Listing flow (FR-011)**: `listings/new` → `open`; `claim` runs `UPDATE scrims SET
  status='confirmed', opponent_team_id=? WHERE id=? AND status='open'` — **first claim wins**; a later
  claim affects 0 rows and is told it's taken.
- **Rejections (FR-017)**: past date/time, self-scrim, claiming a non-`open` listing, acting for a team
  you're not on → all rejected with a clear message.
- **No provisioning (FR-018)**: no transition creates/attaches a server.

## Response expectations (tests, RGL mocked)

- `POST /scrims/propose` (valid, same-format, future) → 302; scrim `pending`, visible as outgoing for
  proposer and incoming for an opponent member.
- Opponent member `POST /scrims/<id>/accept` → `confirmed`, upcoming for both; **non-member** accept →
  403/blocked.
- `POST /scrims/propose` to a different-format team or one's own team, or past time → 400 with message.
- Two members `claim` one listing → first → `confirmed`; second → "no longer available", still one
  confirmed scrim.
- `POST /scrims/<id>/cancel` on a confirmed scrim by either team → `cancelled` (row retained).
- Anonymous or RGL-unlinked access to any `/scrims/*` → redirected (login or link-required).
- No scheduling action creates a server row / provisioning side effect.
