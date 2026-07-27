# Implementation Plan: Scrims Dashboard, Team Rosters & Attendance

**Branch**: `004-scrims-dashboard` | **Date**: 2026-07-23 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-scrims-dashboard/spec.md`

## Summary

Give scrims (feature 003) a home. `/scrims` becomes one **combined dashboard**: every currently
open listing (all formats, soonest first, own-team listings distinguished) plus the viewer's
"my scrims" summary (incoming/outgoing pending, upcoming confirmed), with create-listing and
propose actions top-right. Listings whose time has passed are **auto-removed by query-time
filtering** (no scheduler) and become unclaimable. A new **listing detail page** shows the posting
team's **RGL roster** (fetched from RGL's public team endpoint, cached in SQLite, graceful on
outage), and — for members of the posting team — an **attendance tracker** (self-marking, creator
can mark anyone) with a tally against the format's required player count. The propose flow gains a
**division browser** (US4): a division selector over the current RGL season of the proposing
team's format, backed by a locally cached season directory built via bounded per-request
hydration, listing every registered team — including off-platform teams (labeled), which become
proposable under the shared team identity store. No servers, payments, or new secrets; access
keeps 003's login + RGL-link gate.

## Technical Context

**Language/Version**: Python 3.12 (extends the 001/002/003 app)

**Primary Dependencies**: Flask + Jinja2, `requests` (already present — reused for the RGL team
endpoint), Gunicorn. **No new dependencies.**

**Storage**: SQLite (extends the 003 store) with new tables: `rgl_rosters` (cached team player
lists), `scrim_attendance` (per-listing player statuses), `rgl_roster_meta` (per-team fetch
stamp), and — for the US4 division browser — `rgl_seasons` (season name/format/division-sort map/
fetch stamp) and `rgl_season_teams` (participation + per-team hydration state). Hydrated league
teams are upserted into the existing shared `rgl_teams` identity store (spec Key Entities), which
therefore grows to hold the whole current season (~350 rows across formats) — the propose form's
quick pick switches from `all_teams()` to a new on-platform-only query so it doesn't balloon.
Existing tables unchanged (new tables only — no ALTER migrations needed; `db.py`'s
`CREATE TABLE IF NOT EXISTS` startup schema covers existing databases).

**Testing**: pytest + Flask test client. RGL is **mocked** as in 003, now including the team/roster
and season endpoints. Coverage: combined dashboard content and ordering, expiry filtering +
expired-claim rejection, roster rendering and outage fallback, attendance authorization matrix
(self / creator / non-member) and tally, detail-page visibility; for US4, season parsing, directory
TTL/stale-if-error and bounded hydration (`tests/unit/test_rgl_season.py`) plus the division
browser end-to-end — format scoping, on/off-platform labels, off-platform proposal roundtrip,
RGL-down fallback (`tests/integration/test_propose_discovery.py`); and the shared time filters
(`tests/unit/test_timefmt.py`).

**Target Platform**: same container on `mke`. Outbound HTTPS to `api.rgl.gg` already established
in 003; this feature adds one more **public, keyless** endpoint (`/v0/teams/{teamId}`).

**Project Type**: Web application (extends the single server-rendered Flask app).

**Performance Goals**: dashboard render is pure-SQLite — **zero RGL calls per page load** (SC-001);
roster fetch happens only on the detail page, served from a ~1-hour cache after first fetch
(SC-004); attendance updates are single-row upserts (SC-005); the division browser renders from
the local directory cache — RGL is touched only to fetch a season (~1 call) and to hydrate at most
`RGL_HYDRATE_BATCH` (default 20) not-yet-known teams per request, so steady-state browsing makes
zero RGL calls (SC-006).

**Constraints**: expiry MUST hold at read time with no background jobs (SC-002 — filter in queries,
re-check inside the atomic claim UPDATE); RGL roster calls MUST time out (5 s) and degrade to
cached/absent-with-notice, never an error page (FR-011); attendance writes are authorized
server-side — self-only for members, any-player for the listing creator, nobody else (FR-014) —
and attendance is never rendered for non-members (FR-016); scrim times remain UTC ISO-8601 strings
compared lexicographically (003 convention); the season directory MUST be built without threads or
schedulers — bounded per-request hydration batches only (research §8) — with an honest
"X of Y teams loaded" progress note until complete, and RGL failures degrade the browser to a
notice while the quick pick keeps working (FR-021).

**Scale/Scope**: unchanged from 003 — a small competitive community; tens of teams, hundreds of
scrims, rosters ≤ ~20 players. Trivial for SQLite.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against Constitution v3.0.0 (amended 2026-07-27):

| Principle | Status | Notes |
|---|---|---|
| I. Scrims First, Servers as the Upsell | ✅ Pass | 004 **is** the loop this principle puts first: it builds the free scheduling surface (dashboard, rosters, attendance, opponent discovery) that a team gets without paying a cent. No feature here stands in front of a payment, and nothing is deferred to a paid tier. |
| II. Servers Are Cattle, Not Pets | ✅ N/A | Neither lifecycle (per-scrim or season-term) is touched; scheduling stays schedule-only and creates no workload, Service, PVC, or IP to reclaim. |
| III. Kubernetes-Native Control | ✅ N/A | No cluster interaction. |
| IV. Secure by Default | ✅ Pass | No new secrets (RGL team/season endpoints are public/keyless); attendance and detail visibility enforced server-side against stored memberships, never inferred from submitted ids; scrims area keeps login + RGL-link gate (FR-008). No payment or card data anywhere in this feature. |
| V. Reproducible Images | ✅ Pass | No new dependencies; image build unchanged. |
| VI. Everything as Code | ✅ Pass | Schema additions, routes, templates all in-repo. |
| VII. Right-Size the Blast Radius | ✅ Pass, with note | The concurrency bound on auto-started servers is N/A — 004 starts none. What it does add is RGL fan-out (team, season endpoints), always behind the 5 s timeout + SQLite caches + stale-if-error: rosters fetch only on detail views (~1/h/team); the season directory hydrates at most `RGL_HYDRATE_BATCH` teams per browse request (research §8) — never unbounded fan-out, no threads/schedulers. An RGL outage degrades one page section, never the dashboard or the quick pick. |
| VIII. Free to Schedule, Approved to Provision | ✅ Pass | Everything 004 ships sits in the **free schedule tier**: gated on the Steam-authenticated, RGL-linked pair and nothing more. No transition grants compute, so the provision tier's entitlement and binding rules never come into play. |

**Result**: PASS — no deviations. Under v3.0.0 the scrim surface is the core loop rather than work
outside it, so the Principle I deviation this plan previously carried from 003 no longer exists
(see Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/004-scrims-dashboard/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── dashboard-routes.md          # Phase 1 — combined dashboard, detail page, attendance routes
│   └── propose-discovery-routes.md  # Phase 1 (US4) — division browser in the propose flow
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root) — additions/changes

```text
app/
├── db.py                 # CHANGED: add rgl_rosters, rgl_roster_meta, scrim_attendance,
│                         #          rgl_seasons, rgl_season_teams (US4) to schema
├── rgl.py                # CHANGED: add fetch_team_roster(team_id) → players (steam_id, name, leader
│                         #          flag); US4: fetch_season(season_id) → name/format/division-sort/
│                         #          participating team ids, fetch_team_summary(team_id) for hydration
├── rgl_store.py          # CHANGED: roster persistence — save_roster / get_roster / roster_fetched_at;
│                         #          US4: season directory — ensure_season, hydrate_season_teams(batch),
│                         #          division listing queries, platform_teams() (quick-pick scope)
├── scrims.py             # CHANGED: open_listings + my_open_listings filter out past times;
│                         #          claim's atomic UPDATE also requires a future scheduled_at;
│                         #          get_scrim_for_viewer(detail visibility rule)
├── attendance.py         # NEW: attendance rules — authorize (self vs creator), upsert status,
│                         #      tally vs FORMAT_SIZES {sixes:6, prolander:7, highlander:9},
│                         #      read-only once scheduled_at has passed
├── config.py             # CHANGED: RGL_ROSTER_TTL_SECONDS; US4: RGL_DIRECTORY_TTL_SECONDS (86400),
│                         #          RGL_HYDRATE_BATCH (20)
├── timefmt.py            # NEW: pretty_utc / local_dt / age_since Jinja filters — one readable time
│                         #      format, emitted as UTC inside <time class="ts"> for viewer-local
│                         #      rendering in the browser (research §10)
├── __init__.py           # CHANGED: register the timefmt filters on the app's Jinja env
├── routes/
│   └── scrims.py         # CHANGED: index() renders the combined dashboard; /scrims/listings
│                         #          becomes a redirect to /scrims; NEW GET /scrims/<id> detail;
│                         #          NEW POST /scrims/<id>/attendance; NEW GET /scrims/listings/new
│                         #          (dedicated post-a-listing page; POST endpoint unchanged);
│                         #          US4: new() gains division browser params (team_id, division_id,
│                         #          opponent_id) + hydration; quick pick sourced from platform_teams()
├── templates/
│   ├── base.html         # CHANGED: small shell script rewriting <time class="ts"> elements into
│   │                     #          the viewer's timezone via toLocaleString (research §10)
│   ├── scrims.html       # CHANGED: combined dashboard — two-column grid (research §7): main col =
│   │                     #          open listings (compact 4-col table) + "My matches & listings";
│   │                     #          right rail = "Proposals"; top-right create/propose actions
│   ├── scrim_detail.html # NEW: listing info, team roster, claim form, attendance tracker
│   ├── listing_new.html  # NEW: dedicated post-a-listing page (form moved off the dashboard)
│   ├── listings.html     # REMOVED: folded into scrims.html (route 302s for old links)
│   └── scrim_new.html    # CHANGED (US4): division selector + division team list (on-platform
│                         #          labels, off-platform note, hydration progress, RGL-down
│                         #          notice) alongside the kept quick-pick dropdown
├── static/css/app.css    # CHANGED: scrims layout — 1200px scrims screen, .scrims-cols grid,
│                         #          rail items, cell sub-lines (research §7)

tests/
├── unit/
│   ├── test_rgl_roster.py    # NEW: roster response parsing, 404/timeout/malformed fallbacks (mocked)
│   ├── test_rgl_season.py    # NEW (US4): season parsing, directory build/TTL, bounded hydration,
│   │                         #      stale-if-error, platform_teams() scoping
│   ├── test_attendance.py    # NEW: authz matrix (self/creator/other-member/non-member), statuses,
│   │                         #      tally, read-only after scheduled time, listing-origin only
│   ├── test_timefmt.py       # NEW: pretty_utc/local_dt/age_since — readable UTC text, the <time>
│   │                         #      wrapper the browser localizes, junk/future-stamp fallbacks
│   └── test_scrims.py        # CHANGED: expiry — past listings excluded, expired claim rejected
└── integration/
    ├── test_dashboard.py     # NEW: combined page (listings + my-scrims sections), ordering,
    │                         #      own-team distinction, empty state, /scrims/listings redirect
    ├── test_scrim_detail.py  # NEW: detail visibility, roster shown/degraded, claim from detail,
    │                         #      attendance visible only to team, marking flows end-to-end
    └── test_propose_discovery.py  # NEW (US4): division selector format-scoping, team list +
                              #      labels, off-platform proposal roundtrip, RGL-down fallback
```

**Structure Decision**: Continue the single Flask app and stdlib-`sqlite3` seam. Roster fetching
extends the existing RGL protocol/persistence split (`rgl.py` / `rgl_store.py`) with a per-team
cache keyed by RGL's global team id — rosters are needed for teams whose members never sign in
(e.g. opponents), so they must be fetchable by team id on demand, not only at link time.
Attendance lives in its own small module (`attendance.py`) because its authorization rule
(self-or-creator, listing-team-only, listing-origin-only, frozen after scrim time) is independent
of the 003 scrim state machine and easiest to test in isolation. The dashboard merge happens in
the route/template layer; `scrims.py` query helpers stay single-purpose. The US4 season directory
follows the same protocol/persistence split (`rgl.py` fetches, `rgl_store.py` caches + hydrates in
bounded batches); hydrated teams upsert into the shared `rgl_teams` identity store so 003's
propose validation and FKs work unchanged for off-platform opponents, and the quick pick narrows
to `platform_teams()` (teams with at least one membership) so the league-wide directory doesn't
flood it.

## Complexity Tracking

**No constitution deviations.** Every principle in the check above is PASS or N/A under v3.0.0;
nothing in this feature required a justified violation.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| *(none)* | — | — |

The **Principle I** deviation this section previously recorded — continuing scrim-surface work
ahead of the paid loop — was dissolved by the 2026-07-27 amendment to Constitution v3.0.0, which
makes free scrim scheduling the core loop and paid servers the upsell that attaches to it.
