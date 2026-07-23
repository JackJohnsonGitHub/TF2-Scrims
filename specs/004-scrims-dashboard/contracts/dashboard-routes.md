# Phase 1 Contract: Scrims Dashboard, Detail & Attendance Routes

Server-rendered; every route `@login_required` **and** `@rgl_link_required` (FR-008 — clarification
#3 keeps 003's gate on the whole area). All writes re-check membership server-side; posted ids are
never trusted (003 FR-016 pattern).

## Routes

| Method | Path | Purpose | Maps to |
|---|---|---|---|
| GET | `/scrims` | **Combined dashboard**: all-format open *future* listings (soonest first, own-team rows flagged, inline claim) + my-scrims summary (incoming/outgoing pending, upcoming confirmed) + top-right create/propose actions + empty state. Optional `?format=` filter on the listings section. Layout (research §7): main column = open listings (compact 4-column table, notes/division as sub-lines, no horizontal scroll) then "My matches & listings"; right rail = "Proposals". | FR-001..FR-007 |
| GET | `/scrims/listings` | **302 → `/scrims`** (preserving `?format=`). Old bookmarks/links keep working; page is merged. | research §4 |
| GET | `/scrims/<id>` | **Listing detail**: team, format, division, time, posting age, notes; posting team's roster (cached RGL fetch, stale/absent tolerated); claim form when eligible; attendance tracker when viewer is on the posting team. Visibility per research §6, else 404. | FR-009..FR-013 |
| GET | `/scrims/listings/new` | **Post-a-listing page**: the create-listing form (moved off the dashboard per user UI feedback); submits to the existing `POST /scrims/listings/new`. | FR-004 |
| POST | `/scrims/<id>/attendance` | Upsert one player's status. Form: `player_steam_id`, `status` ∈ `attending` \| `not_attending` \| `unconfirmed`. Self-marking for posting-team members; any player for the listing creator. Redirects back to the detail page. | FR-014..FR-016 |

All 003 routes (`/scrims/new`, `/scrims/propose`, accept/decline/withdraw/cancel,
`/scrims/listings/new`, `.../claim`, `.../cancel`) are **unchanged**; dashboard rows and the
detail page link into them. `claim` additionally rejects expired listings (contract below).

## Behavior contract

- **Gate (FR-008)**: anonymous → login redirect; signed-in but unlinked/team-less → RGL-link
  redirect/message — for *every* route above, including the read-only ones.
- **Expiry (FR-003 / SC-002)**: a listing with `scheduled_at <= now` never appears on the
  dashboard (either section) and cannot be claimed — `claim`'s atomic UPDATE now matches only
  `status='open' AND scheduled_at > now`, so the mid-race expiry loses cleanly ("no longer
  available"). Expired rows are retained (never deleted).
- **Dashboard sections (FR-002/FR-005/FR-007)**: listings section shows team name/tag, format,
  division, scheduled time for every open future listing across formats, ordered by
  `scheduled_at`; the viewer's own teams' listings are visually flagged and carry **no** claim
  affordance; the my-scrims summary reuses 003's incoming/outgoing/upcoming queries and action
  buttons.
- **Roster on detail (FR-010/FR-011)**: if the team's roster stamp is missing/older than the TTL,
  fetch RGL's team endpoint (5 s timeout); success rebuilds the cache, failure falls back to the
  cached roster (with age note) or a friendly "roster unavailable" notice. The listing details
  render in every case — never an error page.
- **Attendance (FR-013..FR-017)**: tracker (statuses + tally vs format size + mark controls)
  renders **only** for posting-team members; non-members see the roster with no attendance data.
  Writes: member may set own status; creator may set anyone's; anything else → 403. Writes to a
  proposal-origin scrim, a cancelled scrim, or after `scheduled_at` → rejected with a clear
  message (tracker shows read-only after scrim time). Tracker (and writes) remain available after
  the listing is claimed → confirmed, until scrim time.
- **Detail visibility (research §6)**: open future listing → any linked user; claimed/confirmed/
  cancelled/expired → members of either participating team only; proposal-origin → participants
  only; everyone else → 404.

## Response expectations (tests; RGL mocked)

- `GET /scrims` → 200; contains open listings from other teams **and** the viewer's my-scrims
  items; a listing with past `scheduled_at` appears in **neither** section; listings ordered
  soonest-first; own-team listing rendered flagged, without a claim control; with zero open
  listings the empty-state call-to-action renders.
- `GET /scrims/listings` → 302 with `Location: /scrims` (query `?format=sixes` preserved).
- `POST /scrims/listings/<id>/claim` on a listing whose time has passed → flash "no longer
  available"; scrim stays `open` in the DB, no `opponent_team_id` set.
- `GET /scrims/<id>` (open future listing, any linked user) → 200 with team info + mocked roster
  names; RGL fetch failure with warm cache → 200 with cached names; failure with cold cache → 200
  with "roster unavailable" notice. Non-member on a confirmed scrim's detail → 404.
- `POST /scrims/<id>/attendance` as posting-team member for own steam id → 303/302, row upserted,
  tally reflects it on reload; as member for a *teammate's* id → 403 (unless creator); as creator
  for any roster/departed id → success; as opponent-team member or non-member → 403; after
  `scheduled_at` passes → rejected, no row change; on a proposal-origin scrim → rejected.
- Attendance never appears in `GET /scrims/<id>` HTML for a non-posting-team viewer (assert absent).
