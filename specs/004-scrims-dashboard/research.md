# Phase 0 Research: Scrims Dashboard, Team Rosters & Attendance

All Technical Context unknowns resolved. Decisions below.

## 1. Roster source — RGL public team endpoint

**Decision**: Fetch rosters from `GET https://api.rgl.gg/v0/teams/{teamId}` (public, keyless —
same API family 003 uses for profiles). Current roster = entries in `players[]` whose `leftAt` is
`null`; each entry carries `steamId`, `name`, `isLeader`.

**Verified live** (2026-07-23, team 14959): response includes `teamId`, `name`, `tag`,
`divisionName`, `seasonId`, and `players[]` with exactly those fields. Departed members appear
with a non-null `leftAt`, so the endpoint alone distinguishes current vs former players.

**Rationale**: Rosters must be fetchable **by team id on demand** — the spec requires showing the
roster of any listing team, including teams none of whose members ever signed in to the app
(FR-010). The profile endpoint 003 uses is keyed by Steam ID and only covers linked users.

**Alternatives considered**: (a) Build rosters from `rgl_memberships` — rejected: only contains
app users, so opponent rosters would be empty or misleading. (b) Scrape rgl.gg team pages —
rejected: fragile, and a structured public API exists.

## 2. Roster freshness — SQLite cache, ~1 h TTL, stale-if-error

**Decision**: Persist rosters in a `rgl_rosters` table (rebuilt atomically per team) with a
per-team fetch stamp in `rgl_roster_meta`. On a detail-page view: if the stamp is older than
`RGL_ROSTER_TTL_SECONDS` (default 3600) or absent, fetch with the existing 5 s timeout; on
success, replace the team's rows and stamp; on failure, serve the cached rows (with their age) or,
with no cache, render the listing with the friendly "roster unavailable" notice (FR-011).

**Rationale**: Keeps RGL entirely off the dashboard path (called only on detail views, at most
once an hour per team), satisfies the outage edge case with zero new dependencies, and follows
003's "timeouts + graceful failure" pattern (Principle VII). Rosters change rarely (roster locks,
weekly adds), so an hour of staleness is immaterial.

**Alternatives considered**: (a) Live fetch every detail view — rejected: adds RGL latency to
every click and hammers a free public API. (b) Refresh only on RGL link/refresh — rejected:
opponent teams' rosters would never refresh. (c) Background refresher job — rejected: scheduler
complexity the page-load path doesn't need (see §3 rationale).

## 3. Auto-removal of past listings — query-time filtering, no scheduler

**Decision**: Expiry is a **read-side rule**: `open_listings()` and `my_open_listings()` add
`AND s.scheduled_at > :now`, and `claim()`'s atomic UPDATE gains `AND scheduled_at > :now` so an
expired listing can never be claimed even in a race. No status flip, no background job; an
expired row simply stops matching "open" queries (record retained per clarification).

**Rationale**: Timestamps are already stored as ISO-8601 UTC strings that compare
lexicographically (003 convention), so the filter is one predicate. SC-002 ("at any moment, zero
past listings visible") holds *exactly* at read time — a cron-style sweeper would only approximate
it between runs while adding a scheduler, a new failure mode, and test complexity. The claim-side
guard closes the "expires while being viewed" edge case.

**Alternatives considered**: (a) Background job flipping status to `expired` — rejected as above;
can be added later if anything ever needs to *enumerate* expired listings cheaply. (b) Flipping
status lazily on read — rejected: writes during GETs for no behavioral gain.

## 4. Combined dashboard — merge `/scrims/listings` into `/scrims`

**Decision**: `/scrims` renders the combined dashboard (clarified in spec): all-format open
listings (soonest first, own-team rows flagged, claim affordances inline) plus the my-scrims
summary (incoming/outgoing pending, upcoming confirmed) and top-right create/propose actions.
`/scrims/listings` becomes a `302` redirect to `/scrims` (preserving any `format` query arg) so
old bookmarks and in-flight links keep working; `listings.html` is folded into `scrims.html`.

**Rationale**: Direct implementation of clarification #1. A redirect is cheaper than maintaining
two views of the same data, and the existing `open_listings(format)` helper already serves the
merged page.

**Alternatives considered**: keeping both pages (rejected by clarification), or deleting
`/scrims/listings` outright (rejected: gratuitous 404s for known URLs).

## 5. Attendance model — explicit rows, self-or-creator writes, frozen after scrim time

**Decision**: New `scrim_attendance` table keyed `(scrim_id, player_steam_id)` with a snapshotted
`player_name`, `status` ∈ {attending, not_attending, unconfirmed}, `marked_by`, `updated_at`.
Absence of a row = unconfirmed (the default). Writes allowed only when: the scrim's `origin` is
`listing`; the actor is a member of the posting team; and the actor marks **their own**
`player_steam_id` — or is the scrim's `created_by`, who may mark anyone (clarification #4). The
tracker renders for posting-team members only, stays available after claim/confirm, and becomes
read-only once `scheduled_at` passes (FR-017). Tally compares `attending` count to
`FORMAT_SIZES = {sixes: 6, prolander: 7, highlander: 9}` (FR-015).

**Rationale**: Roster players are identified by the `steamId` RGL already returns — the same
identity space as app accounts, which makes "mark yourself" a direct equality check and works for
players who never sign in (creator marks them). Snapshotting `player_name` keeps departed players
renderable and flagged (spec edge case) after they leave the live roster.

**Alternatives considered**: (a) Keying by a roster-row id — rejected: roster rows are rebuilt on
refresh, which would orphan attendance. (b) Only storing non-default statuses — rejected:
"explicitly unconfirmed" (creator resetting someone) and "never marked" are worth distinguishing
in `marked_by`/`updated_at` terms, and one nullable-free row shape is simpler.

## 6. Detail-page visibility

**Decision**: `GET /scrims/<id>` is visible to any RGL-linked user while the scrim is an **open,
future listing** (that's what the dashboard links to). Once it is claimed/confirmed/cancelled or
past, the detail page is visible only to members of either participating team; others get 404.
Proposal-origin scrims have no public detail page (participants only). Attendance renders only
for posting-team members in all cases (FR-016).

**Rationale**: Matches what the dashboard exposes (open listings are public to the linked
community; everything else already lives in the participants' own my-scrims views) and keeps
FR-017 satisfied — the posting team retains tracker access via the same URL after a claim.

**Alternatives considered**: making every scrim detail public to linked users — rejected: leaks
match arrangements between other teams with no user story requiring it.

## 7. Dashboard layout & create-listing entry — user UI feedback (2026-07-23, post-implementation)

**Decision**: The combined dashboard is a two-column grid (2:1, collapsing to one column under
900px). The left/main column holds **Open listings** (the primary content) with **My matches &
listings** (upcoming confirmed + own open listings) directly beneath; the right rail holds
**Proposals** (incoming + outgoing) as compact stacked items rather than tables. **Post an open
listing** moved off the dashboard to a dedicated page (`GET /scrims/listings/new`, same POST
endpoint; validation errors return to the form page). Listing rows were compacted so the table
fits with **no horizontal scrolling**: notes fold under the team name and division under the
format as muted sub-lines, times render as `YYYY-MM-DD HH:MM` UTC, and the scrims screen widens
the page shell to 1200px (other screens keep 960px). `overflow-x: auto` on the grid's cards stays
as a safety net only.

**Rationale**: Direct user feedback after using the implemented dashboard, in three iterations:
(1) proposals belong in a side rail with matches/listings grouped in a box; (2) "My matches &
listings" reads better on the left, under the listings, than in the rail; (3) the horizontal
scrollbar on the listings table had to go — the root cause was a 6-column table inside a
two-thirds-width card on a 960px page, so the fix was widening the screen and folding low-priority
columns (notes, division) into sub-lines instead of hiding the overflow.

**Alternatives considered**: (a) single stacked column (original implementation) — rejected by
user: scannable schedulable content should dominate, side matter shouldn't push it around;
(b) inline post-listing form on the dashboard (original) — rejected by user: belongs on its own
page; (c) keeping the 6-column table with a scrollbar — rejected by user; hiding the scrollbar
without compacting would have re-introduced the table bleeding under the rail.

## 8. Season directory for the division browser (US4) — endpoints verified live 2026-07-23

**What RGL actually offers** (probed live): `GET /v0/seasons/{seasonId}` returns the season name,
`formatName`, a `divisionSorting` map (**division id → sort rank, no names**), and
`participatingTeams` as a **flat list of team ids** (~116 for 6s Season 20). There is **no**
divisions endpoint, **no** team search, and **no** bulk team fetch — `/v0/divisions/*`,
`/v0/search/teams`, `/v0/searches/teams`, `/v0/teams/paged` all 404. Division names and team
names/tags come only from per-team `GET /v0/teams/{id}` calls (which return `divisionId`,
`divisionName` — same endpoint the roster cache already uses).

**Decision — locally cached season directory with bounded per-request hydration**:

- **Which season**: the proposing team's stored `season_id` (saved at RGL link time from
  `currentTeams`) — it *is* the current season for that team's format/region; no extra discovery
  call. Refreshing the RGL link updates it.
- **Directory build**: `ensure_season(season_id)` fetches the season once (TTL
  `RGL_DIRECTORY_TTL_SECONDS`, default 24 h — registrations change rarely) and records the
  participation list. Each browse request then **hydrates at most `RGL_HYDRATE_BATCH` (default
  20) not-yet-hydrated teams** via the team endpoint, upserting them into `rgl_teams` (shared
  identity store) and stamping `rgl_season_teams`. Until hydration completes the browser shows the
  divisions/teams cached so far plus an honest "X of Y teams loaded — refresh to load more" note
  (~6 refreshes for a full 116-team season). Steady state: zero RGL calls to browse.
- **Division grouping/order**: group by hydrated `division_id`/`division_name`; order divisions by
  the season's `divisionSorting` rank (stored as JSON on `rgl_seasons`).
- **Failures**: season or team fetch failures follow the roster pattern — stale-if-error, friendly
  notice, quick pick unaffected (FR-021). No threads, no schedulers (Constitution I/VII posture).

**Rationale**: ~116 sequential team fetches inline would take tens of seconds — unacceptable for a
page load — while a scheduler/thread adds a failure mode the constitution's smallest-thing rule
doesn't justify. Bounded batches keep every request predictable (~20 × ~250 ms worst case, only
while the directory warms), the work happens exactly when a user wants the data, and the cache
makes it a one-time cost per season per day.

**Alternatives considered**: (a) full inline fetch on first browse — rejected: 30 s+ request;
(b) background thread/cron sync — rejected: threading in Gunicorn workers + a scheduler for a
once-a-day dataset is complexity the read path doesn't need; can be revisited if seasons grow;
(c) operator CLI sync only — rejected: makes a self-service flow depend on the operator;
(d) hydrating only the selected division's teams — rejected: team→division mapping is only
learnable BY hydrating (the season payload has no division names), so selective hydration can't
know which teams belong to the chosen division.

## 9. Quick-pick scoping once `rgl_teams` holds the whole league (US4)

**Decision**: the propose form's quick dropdown switches from `all_teams()` to a new
`platform_teams()` query — same-format teams having **at least one membership row** (a member on
the platform). The division browser is the path to everyone else.

**Rationale**: hydration grows `rgl_teams` to every registered team in the season (~350 across
formats); `all_teams()` would turn the "quick" pick into an unusable league-wide dropdown and
erase the browser's purpose. Membership presence is exactly the "on the platform" signal the spec
labels teams with (FR-019).

**Alternatives considered**: keeping `all_teams()` — rejected as above; a separate "known teams"
flag column — rejected: membership rows already encode it, no new state needed.
