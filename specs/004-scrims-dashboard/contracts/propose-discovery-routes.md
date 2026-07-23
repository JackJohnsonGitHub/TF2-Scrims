# Phase 1 Contract: Division Browser in the Propose Flow (US4)

Server-rendered; `@login_required` + `@rgl_link_required` as everywhere in the scrims area
(FR-008). No new POST endpoints — the browser only changes how the opponent is *found*; proposal
creation stays `POST /scrims/propose` (003 contract, unchanged).

## Routes

| Method | Path | Purpose | Maps to |
|---|---|---|---|
| GET | `/scrims/new` | **Extended propose form.** Optional query params drive the browser: `team_id` (which of my teams proposes — selects the format and its current `season_id`), `division_id` (chosen division), `opponent_id` (team picked from the browser, pre-selected as opponent). Renders: my-team selector; the kept **quick pick** (on-platform same-format teams via `platform_teams()`); the **division selector** (hydrated divisions of the season, ordered by RGL's division sorting); and, when `division_id` is chosen, that division's team list. | FR-018, FR-019, FR-021 |
| POST | `/scrims/propose` | Unchanged (003). Accepts any `opponent_team_id` that exists in `rgl_teams` and passes same-format / not-own / future-time validation — including off-platform teams hydrated by the browser. | FR-020 |

## Behavior contract

- **Season scoping (FR-018)**: the division selector shows only divisions of the **current season
  of the selected proposing team's format** (the team's stored `season_id`). Changing the
  proposing team re-scopes the browser; other formats' divisions never appear.
- **Directory build (research §8)**: on browser render, `ensure_season` refreshes the season
  within a 24 h TTL, then at most `RGL_HYDRATE_BATCH` (default 20) pending teams are hydrated in
  that request. While any teams remain pending, the browser shows the hydrated divisions/teams
  plus **"Loaded X of Y teams — refresh to load more."** Steady state makes zero RGL calls.
- **Team list (FR-019)**: teams of the chosen division, organized under their division name, each
  labeled **on the platform** (has ≥ 1 linked member) or **not on the platform yet**; every team
  except the user's own is selectable as opponent (selection pre-fills the propose form via
  `opponent_id`). The user's own team renders unselectable.
- **Off-platform proposal (FR-020)**: submitting with an off-platform opponent creates a standard
  `pending` proposal; the success flash and the outgoing list note that a response requires
  someone from that team to join and link. Withdraw works as always; accept/decline become
  possible once a member links (membership check is unchanged 003 logic).
- **Quick pick (FR-021)**: sourced from `platform_teams()` — same-format, membership-backed teams
  only (never the whole hydrated league). If RGL is unreachable, the division browser area shows a
  friendly notice (stale directory still browsable if previously built); the quick pick and the
  rest of the form keep working.

## Response expectations (tests; RGL mocked)

- `GET /scrims/new?team_id=<sixes team>` → 200; division selector lists only that season's
  divisions; a mocked highlander season's divisions never render.
- With pending hydrations, exactly `RGL_HYDRATE_BATCH` team fetches occur per request (assert call
  count on the mock) and the progress note shows correct X/Y; a fully hydrated season triggers
  zero team fetches.
- `GET /scrims/new?team_id=..&division_id=..` → 200; lists that division's hydrated teams with
  correct on/off-platform labels; the viewer's own team is present but not selectable.
- Choosing an off-platform team (`opponent_id`) pre-selects it; `POST /scrims/propose` with it →
  302; scrim row `pending` with that `opponent_team_id`; outgoing list shows the
  awaiting-them-to-join note; withdraw works; an unrelated linked user cannot accept (403 —
  no membership).
- Season fetch failure with no cached season → friendly notice in the browser area, quick pick
  still renders, form still submits via quick pick. Season fetch failure with a cached season →
  stale directory still browsable.
- Quick pick contains on-platform same-format teams only, even after full hydration of ~100+
  league teams (assert a hydrated off-platform team is absent from the dropdown but present in
  the division list).
