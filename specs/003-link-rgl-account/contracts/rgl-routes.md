# Phase 1 Contract: RGL Link Routes

Server-rendered; all routes `@login_required` (feature 002). RGL data fetched from the public API on
link/refresh only.

| Method | Path | Purpose | Maps to |
|---|---|---|---|
| GET | `/account` | Account area: RGL link status (linked / not linked), profile name, current teams grouped by format, status badges, last-refreshed time. | FR-004, FR-007 |
| POST | `/rgl/link` | Fetch the RGL profile for the signed-in SteamID; upsert `rgl_links` + `rgl_teams` + `rgl_memberships`; redirect back to `/account`. | FR-001, FR-002, FR-003 |
| POST | `/rgl/refresh` | Re-fetch and update stored profile/teams/memberships; update `last_refreshed_at`. | FR-005 |
| POST | `/rgl/unlink` | Delete the user's `rgl_links` + `rgl_memberships`; keep shared `rgl_teams`. | FR-005 |

## Behavior contract

- **Auto-detected (FR-002)**: `/rgl/link` uses `session` SteamID only — no RGL id/URL is accepted from
  the form.
- **Outcomes (FR-006)**: link sets `state` = `linked` (has ≥1 team), `no_team` (profile but all
  formats null), or `no_profile` (404/empty). RGL unavailable → flash a retry message, leave prior
  state intact, page still renders (SC-008).
- **Status badges (FR-007)**: verified / banned / on-probation shown if present; never block linking.
- **Refresh (FR-005)**: rebuilds memberships (drops teams the user left); updates team details.

## Response expectations (tests, RGL mocked)

- `POST /rgl/link` with a mocked profile that has teams → 302 to `/account`; `rgl_links.state=linked`,
  team rows + membership rows exist; `/account` shows the team names by format.
- Mocked profile with no teams → `state=no_team`; `/account` shows "no current team".
- Mocked 404 → `state=no_profile`; friendly message; no team rows.
- Mocked timeout on `/rgl/refresh` → retry flash; previously stored data unchanged; page 200.
- `POST /rgl/unlink` → link + memberships gone; `/account` shows "not linked".
- Anonymous access to any `/rgl/*` → 302 to `/login` (002 guard).
