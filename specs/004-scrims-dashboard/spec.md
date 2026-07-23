# Feature Specification: Scrims Dashboard, Team Rosters & Attendance

**Feature Branch**: `004-scrims-dashboard`

**Created**: 2026-07-23

**Status**: Draft

**Input**: User description: "This new Feature will be the Scrims feature. This Will involve The logged in user to Click the scrims Icon seen in the header. Clicking that will bring you the scrims open listing dashboard. This will show all the scrims that people have requested. Past listings will be auto removed. At the top right should be the ability to create a listing or propose a listing to a specific team. When you click on a listing It gives you the ability to see the people on the team. if its your own team's listing you should be able to have an attendance tracker."

## Clarifications

### Session 2026-07-23

- Q: What should the header "Scrims" entry land on? → A: One combined page — the open-listings
  dashboard plus a "my scrims" summary (pending proposals, upcoming confirmed matches) on the same
  screen; it replaces the separate "my scrims" landing page.
- Q: What does "past listings auto removed" mean once a listing's scheduled time passes? → A: Hidden
  from the dashboard and unclaimable, but the record (including attendance data) is retained — not
  deleted.
- Q: Who can view the dashboard, listing details, and rosters? → A: Only signed-in users with a
  linked RGL team (keep feature 003's gate on the whole scrims area); unlinked users are directed to
  link RGL first.
- Q: Who can update attendance on a team's listing? → A: Self + creator — a team member with an
  account sets only their own status; the listing's creator can set any roster player's status
  (including players without app accounts). All team members can view the tracker.
- Q: How should the combined dashboard be laid out? (post-implementation UI feedback) → A: Open
  listings are the primary, widest column with "My matches & listings" (upcoming confirmed matches
  + the viewer's own open listings) directly beneath them; a narrower side rail holds "Proposals"
  (incoming + outgoing). Collapses to a single column on narrow screens.
- Q: Where does "post an open listing" live? (post-implementation UI feedback) → A: On its own
  dedicated page, reached from the dashboard's top-right "New listing" action — not an inline form
  on the dashboard.
- Q: How much detail per dashboard listing row? (post-implementation UI feedback) → A: Compact
  rows — notes and division render as secondary lines beneath the team and format, times show as
  compact UTC (date + hh:mm), and the listings table must fit its panel with no horizontal
  scrolling.
- Q: When browsing RGL teams by division in the propose flow, which teams are listed? → A: The
  current RGL season's divisions and teams for the **same format** as the selected proposing team
  only — every listed team is a legal opponent (same-format rule, 003 FR-012).
- Q: Can you propose to an RGL team with no member on the platform yet? → A: Yes — the proposal is
  created as a normal pending proposal; such teams are clearly labeled (e.g. "not on the platform
  yet") so the proposer knows a reply requires someone from that team to sign in and link, and the
  proposer can withdraw as usual.
- Q: Where does the division browser live — and does the current opponent dropdown stay? → A: In
  the propose form: a division selector loads that division's teams to pick as opponent; the
  existing quick dropdown of already-known (on-platform) teams stays as a fast path.

## User Scenarios & Testing *(mandatory)*

Feature 003 established the two scheduling flows (directed propose → accept/decline and open
listing → claim). This feature gives scrims a **home**: a single combined dashboard reached from
the "Scrims" entry in the site header that shows every currently open listing alongside a summary
of the viewer's own scrims (pending proposals and upcoming confirmed matches), automatically drops
listings whose time has passed, and offers the create-listing and propose-to-team actions in one
place. It also deepens
a listing from a row into a page: opening a listing shows **who is on the listing team** (its player
roster), and when the listing belongs to one of *your* teams, an **attendance tracker** lets the
team record which players will show up.

### User Story 1 - Browse the open scrims dashboard from the header (Priority: P1)

As a signed-in user with a linked RGL team, I click "Scrims" in the site header and land on the
scrims dashboard: one combined page with a list of every open scrim listing other teams have posted — team, format,
division, and scheduled date/time — plus a summary of my own scrims (incoming and outgoing pending
proposals and upcoming confirmed matches for my teams). Listings whose time has already passed are
removed automatically. From the top right of the dashboard I can start a new open listing or a
directed proposal to a specific team.

**Why this priority**: This is the feature's core promise — one place to see everything currently
schedulable. Without the dashboard, the roster and attendance stories have no surface to live on.

**Independent Test**: Sign in, click "Scrims" in the header, and confirm every open listing (and
only open listings — none with a past date/time) is shown with its team, format, and time; confirm
the create-listing and propose actions are present at the top right and lead to the existing flows.

**Acceptance Scenarios**:

1. **Given** a signed-in, RGL-linked user on any page, **When** they click "Scrims" in the header,
   **Then** the scrims dashboard loads showing all currently open listings with team name, format,
   division, and scheduled date/time.
2. **Given** an open listing whose scheduled date/time has passed, **When** the dashboard is viewed,
   **Then** that listing does not appear and can no longer be claimed — with no manual cleanup by
   anyone.
3. **Given** the dashboard is showing, **When** the user looks at the top right, **Then** they find
   both a "create a listing" action and a "propose to a specific team" action, each leading into the
   corresponding existing scheduling flow.
4. **Given** no open listings exist, **When** the dashboard is viewed, **Then** a friendly empty
   state invites the user to post the first listing.
5. **Given** the user's own team has an open listing, **When** the dashboard is viewed, **Then**
   that listing is visibly distinguished as their own team's (and is not offered for them to claim).
6. **Given** a user whose teams have pending proposals or upcoming confirmed matches, **When** the
   dashboard is viewed, **Then** a "my scrims" summary on the same page shows those items (the
   dashboard replaces the previous separate "my scrims" landing page).

---

### User Story 2 - See the people on a listing's team (Priority: P2)

As a user browsing the dashboard, I click on a listing and see its detail: the listing's team,
format, division, scheduled time — and the roster of players currently on that team, so I can judge
who my team would actually be playing against before claiming.

**Why this priority**: Knowing the opponent's players is the main reason to click into a listing;
it turns a bare row into enough information to decide whether to claim.

**Independent Test**: From the dashboard, open a listing posted by another team and confirm the
listing's details and that team's current player list are shown; confirm a claim can be made from
the detail view.

**Acceptance Scenarios**:

1. **Given** an open listing from another team, **When** the user clicks it on the dashboard,
   **Then** a listing detail view opens showing the listing's team, format, division, scheduled
   time, and the players currently on that team.
2. **Given** the listing detail view, **When** the roster is shown, **Then** each entry shows the
   player's name as known to the league.
3. **Given** the league's roster information is temporarily unavailable, **When** the detail view
   opens, **Then** the listing details still render with a friendly notice in place of the roster —
   no error page.
4. **Given** an eligible same-format team member views another team's listing detail, **When** they
   choose to claim it, **Then** the existing claim flow completes from the detail view.

---

### User Story 3 - Track attendance on my own team's listing (Priority: P3)

As a member of the team that posted a listing, when I open my own team's listing I get an
attendance tracker: our roster with each player's status (attending / not attending / unconfirmed).
I can set my own status, the teammate who created the listing can set anyone's (including players
who never signed in to the app), and we all see a tally of confirmed players against the number the
format needs — so we know before scrim time whether we can field a full team.

**Why this priority**: Valuable coordination on top of the listing, but it only matters once the
dashboard (US1) and roster view (US2) exist.

**Independent Test**: As the creator of your team's listing, mark several players attending / not
attending and confirm the tally updates and persists; as a non-creator teammate, confirm you can
set your own status but not others'; confirm a user from another team viewing the same listing
sees the roster but no attendance tracker.

**Acceptance Scenarios**:

1. **Given** a listing posted by one of my teams, **When** I open its detail view, **Then** the
   roster appears as an attendance tracker with each player's current status (attending / not
   attending / unconfirmed, defaulting to unconfirmed).
2. **Given** the attendance tracker, **When** I set my own status (or, as the listing's creator,
   any player's status), **Then** the change is saved, is visible to my teammates when they view
   the listing, and the confirmed-player tally updates against the format's required player count.
3. **Given** I am a team member who did not create the listing, **When** I try to change a
   teammate's status, **Then** the tracker does not allow it — I can only set my own.
4. **Given** a listing belonging to a team I am **not** on, **When** I open its detail view,
   **Then** I see the roster but no attendance tracker and no attendance information.
5. **Given** attendance marks were recorded, **When** the listing is claimed by an opponent
   (becoming a confirmed scrim), **Then** the team's attendance tracker remains available to the
   team until the scheduled time passes.

---

### User Story 4 - Find any RGL opponent when proposing a scrim (Priority: P2)

As a captain proposing a scrim, after choosing which of my teams I'm proposing as, I can open a
division selector that lists the current RGL season's divisions for that team's format, pick a
division, and see **all** RGL teams registered in it — organized by division and including teams
whose members haven't joined this platform yet (clearly labeled) — and choose any of them as my
opponent. The existing quick pick of teams already on the platform stays available as a fast path.

**Why this priority**: Today the opponent picker only offers teams whose members already signed in
here, which is nearly useless for finding real opponents; browsing the league's actual divisions
makes the propose flow work against the whole RGL field.

**Independent Test**: On the propose form, select your team, open the division selector, and
confirm it lists only that format's current-season divisions; pick one and confirm every
registered team in it appears with an on-platform/off-platform label; propose to an off-platform
team and confirm a normal pending (withdrawable) proposal is created with clear "they need to
join to respond" messaging; confirm the quick dropdown still works.

**Acceptance Scenarios**:

1. **Given** I selected my Sixes team as the proposer, **When** I open the division selector,
   **Then** I see the current RGL season's Sixes divisions only (never other formats').
2. **Given** a chosen division, **When** its team list loads, **Then** all RGL teams registered in
   that division are shown, organized by division, each indicating whether it is on the platform.
3. **Given** I pick an off-platform team and submit a valid proposal, **Then** a normal pending
   proposal is created and my outgoing list shows it with a note that a response requires someone
   from that team to join and link.
4. **Given** RGL cannot be reached, **When** I open the division browser, **Then** a friendly
   notice appears and the quick pick of already-known teams keeps working.
5. **Given** any team chosen via the browser, **Then** the existing rules still hold — same format
   only, no proposing to my own team, future date/time.

---

### Edge Cases

- **Listing expires while being viewed** — a user has the dashboard or a detail view open as the
  scheduled time passes; a claim attempted after expiry is rejected with a clear "no longer
  available" message.
- **Signed-out visitor** — the Scrims area is for signed-in users; a signed-out visitor is asked to
  sign in first (consistent with the rest of the app's gating).
- **Signed-in but not RGL-linked / no team** — the whole scrims area keeps feature 003's gate: the
  user is directed to link their RGL account / join a team before they can view the dashboard,
  listings, or rosters.
- **Roster source unavailable** — the league can't be reached when opening a detail view: listing
  details still render, roster area shows a friendly retry message.
- **Roster changed since posting** — players joined/left the team after the listing was posted; the
  detail view shows the team's *current* roster, and attendance entries for departed players remain
  visible but flagged as no longer on the team.
- **Player without an app account** — roster players who never signed in are still listed and still
  trackable in attendance (the listing's creator marks their status for them).
- **Multiple own-team listings** — a team with several open listings has an independent attendance
  tracker per listing.
- **Own team's listing among others** — a user's own listing is never claimable by them and is
  visually distinguished on the dashboard.
- **Division browser with RGL down** — the division/team lists can't be fetched: friendly notice
  in the browser; the quick pick of already-known teams still works, and the rest of the propose
  form is unaffected.
- **My own team appears in the browsed division** — it is shown (it is registered there) but not
  selectable as an opponent (no self-scrim).
- **Off-platform opponent never joins** — the proposal simply stays pending; the proposer can
  withdraw it at any time (existing 003 mechanics — no expiry is added to proposals).

## Requirements *(mandatory)*

### Functional Requirements — Dashboard

- **FR-001**: The site header MUST include a "Scrims" entry, visible on every page to signed-in
  users, that leads to the scrims dashboard.
- **FR-002**: The dashboard MUST list every currently open scrim listing across all teams and
  formats, showing at least the posting team (name/tag), format, division where known, and the
  scheduled date/time. Rows stay compact: division and notes render as secondary detail under
  format and team, times show as compact UTC (date + hh:mm), and the listings table MUST fit its
  panel without horizontal scrolling.
- **FR-003**: Listings whose scheduled date/time has passed MUST be removed from the dashboard
  automatically — they MUST NOT appear in the open list and MUST NOT be claimable — without any
  manual action by users or the operator. The underlying record is retained (not deleted) for the
  teams involved.
- **FR-004**: The dashboard MUST present, in its top-right action area, an action to create a new
  open listing and an action to propose a scrim to a specific team, each entering the corresponding
  existing scheduling flow (feature 003). The create-listing action MUST lead to a dedicated
  post-a-listing page; the form does not live on the dashboard.
- **FR-005**: The dashboard MUST visibly distinguish listings posted by the viewing user's own
  team(s) from other teams' listings, and MUST NOT offer the user a claim action on their own
  team's listings.
- **FR-006**: The dashboard MUST order listings by soonest scheduled time first, and MUST show a
  friendly empty state (with a call to action to post a listing) when no open listings exist.
- **FR-007**: The dashboard page MUST also include a "my scrims" summary for the viewer's teams —
  incoming and outgoing pending proposals and upcoming confirmed matches — on the same page as the
  open listings; it replaces the previous separate "my scrims" landing page, and existing
  accept/decline/withdraw/cancel actions remain reachable from it. Layout: open listings are the
  primary (widest) column with "My matches & listings" (upcoming matches + the viewer's own open
  listings) beneath them; incoming/outgoing proposals sit in a narrower "Proposals" side rail;
  the page collapses to one column on narrow screens.
- **FR-008**: The scrims area (dashboard, listing details, rosters) MUST keep feature 003's access
  gate: it requires a signed-in user with a linked RGL team. Signed-out visitors are directed to
  sign in; signed-in users without a linked team are directed to link RGL / join a team.

### Functional Requirements — Listing detail & roster

- **FR-009**: Clicking a listing on the dashboard MUST open a detail view showing the listing's
  team, format, division where known, scheduled date/time, and posting age.
- **FR-010**: The detail view MUST show the roster of players currently on the listing's team, as
  known to the league, each with their player name.
- **FR-011**: If roster information cannot be retrieved, the detail view MUST still render the
  listing's details with a clear, friendly notice in place of the roster — never an error page.
- **FR-012**: An eligible user (per feature 003's rules) MUST be able to claim the listing from its
  detail view; ineligible users see why they cannot (not signed-in to a same-format team, own
  listing, or listing no longer open).

### Functional Requirements — Opponent discovery (propose flow)

- **FR-018**: The propose form MUST offer a division browser: once the user selects their
  proposing team, a division selector MUST list the current RGL season's divisions for that team's
  format only; selecting a division MUST show all RGL teams registered in it, organized by
  division.
- **FR-019**: The division browser MUST include teams with no member on this platform, each
  clearly labeled as not on the platform yet; any listed team (except the user's own) MUST be
  selectable as the opponent.
- **FR-020**: Proposing to an off-platform team MUST create a standard pending proposal (feature
  003 mechanics — withdrawable by the proposer; acceptable/declinable once a member of that team
  signs in and links), and the proposer MUST be told that a response requires the opposing team to
  join the platform.
- **FR-021**: The existing quick pick of already-known same-format teams MUST remain available
  alongside the division browser; when the league cannot be reached, the browser MUST degrade to a
  friendly notice while the quick pick and the rest of the propose form keep working.

### Functional Requirements — Attendance tracker

- **FR-013**: When the viewer is a member of the listing's team, the detail view MUST present the
  roster as an attendance tracker: each player carries a status of attending, not attending, or
  unconfirmed (the default).
- **FR-014**: A member of the listing's team MUST be able to set their **own** attendance status;
  the listing's **creator** MUST be able to set **any** roster player's status (covering players
  without app accounts). No other user may change attendance. Each change MUST be persisted and
  reflected to all team members viewing the listing.
- **FR-015**: The tracker MUST show a tally of players marked attending against the number of
  players the listing's format requires (Sixes 6, Prolander 7, Highlander 9).
- **FR-016**: Attendance information MUST be visible and editable only to members of the listing's
  team — never to other teams or in the general listing view.
- **FR-017**: The attendance tracker MUST remain available to the team on that scrim after the
  listing is claimed (confirmed), until the scheduled time passes.

### Key Entities *(include if feature involves data)*

- **Scrim listing** *(existing, extended)*: an open scrim posted by a team (feature 003). Extended
  behavior: expires automatically once its scheduled date/time passes — expired listings leave the
  open pool and cannot be claimed, but remain on record.
- **Team roster / roster player**: the players currently on an RGL team as known to the league —
  player name and league identity, independent of whether the player has ever signed in to the
  app. Sourced from the league, refreshable like other team data.
- **Attendance record**: for one listing and one roster player, the player's status (attending /
  not attending / unconfirmed) with who last updated it and when. Exists only for listings of the
  viewer's own team; retained with the scrim record.
- **RGL division (current season)**: a format's competitive bracket in the league's current
  season — division name and the RGL teams registered in it. Sourced from the league on demand for
  the propose flow's browser; teams discovered this way join the same shared team identity store
  (keyed by RGL team id) that linked users' teams use, whether or not any of their members are on
  the platform.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From any page, a signed-in RGL-linked user reaches the scrims dashboard in one click
  and can identify every open listing's team, format, and scheduled time — and their own pending
  and upcoming scrims — without further navigation.
- **SC-002**: At any moment, zero listings with a past scheduled time appear on the dashboard, with
  no manual cleanup ever performed by users or the operator.
- **SC-003**: Both scheduling flows (create a listing, propose to a team) are reachable from the
  dashboard's top-right actions in a single click.
- **SC-004**: A user can open any listing and see the posting team's current player list; when the
  league is unreachable, the listing still renders with a clear notice instead of an error.
- **SC-005**: A listing creator can record attendance for any roster player (and a teammate their
  own status) in under ~10 seconds per player, the confirmed tally always matches the marks, and
  attendance is never visible to users outside the team.
- **SC-006**: From the propose form, a captain can find and select any current-season same-format
  RGL team — including one with no members on the platform — via the division selector in under
  ~30 seconds, and the resulting proposal behaves exactly like any other pending proposal.

## Assumptions

- **"Auto removed" means expired, not erased**: a listing whose scheduled time passes disappears
  from the dashboard and becomes unclaimable automatically, but the record is kept (consistent with
  feature 003's "cancelled, not silently deleted" approach) so teams retain their history and
  attendance context.
- **The dashboard shows all formats**: RGL-linked users browse listings across all formats, not
  just their own teams' formats; eligibility rules (same format, not your own team) continue to
  gate *acting* on a listing, exactly as feature 003 defined.
- **Roster comes from the league**: "the people on the team" is the team's current player list per
  RGL (keyed by the same team identity feature 003 stores), not just users who have signed in to
  this app; it can be refreshed the same way linked team data is refreshed.
- **Attendance is self-service with a creator override**: team members with accounts set their own
  status; the listing's creator can set anyone's, since some players will never have app accounts.
  The whole listing team can *view* the tracker.
- **Attendance stays useful after a claim**: the tracker's purpose is knowing who will show up at
  scrim time, so it remains accessible to the team after an opponent claims the listing, until the
  scheduled time passes.
- **The header already carries a "Scrims" entry** (visible in the current app shell); this feature
  defines its destination as the combined scrims dashboard (open listings + "my scrims" summary).
- **Division and team data come from the league**: the browser reflects RGL's current-season
  registration data, fetched on demand; freshness/caching cadence is an implementation decision
  (like rosters). Off-platform teams selected as opponents are stored under the same RGL team
  identity used everywhere else, so nothing changes for them when their members later join.
- **Out of scope**: notifications/reminders about attendance or expiring listings; attendance
  tracking for directed proposals or for the opposing team; match results or history pages;
  filtering/search on the dashboard beyond the default soonest-first ordering; searching teams by
  name in the propose flow (browsing is by division in this phase); notifying off-platform teams
  about proposals (they discover them by joining); any server provisioning (unchanged from feature
  003 — scheduling never touches servers).

## Dependencies

- **Feature 002 — Sign in with Steam**: the signed-in identity gating the scrims area.
- **Feature 003 — Link RGL Account & Schedule Scrims**: team identities, the open-listing and
  directed-proposal flows, claim semantics, and eligibility rules this dashboard surfaces.
