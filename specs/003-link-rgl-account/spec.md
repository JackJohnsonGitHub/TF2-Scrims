# Feature Specification: Link RGL Account & Schedule Scrims

**Feature Branch**: `003-link-rgl-account`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "After a user signs in with his steam account he is then able to link their team's RGL (rgl.gg) account. The main use is so that when two teams want to have a scrimmage match they can schedule it on the website."

## Clarifications

### Session 2026-07-13

- Q: What should this feature (003) build? → A: Both the RGL/team link **and** basic scrim scheduling between two teams.
- Q: Which team does a user schedule as when they have several RGL teams? → A: Store all current teams; the user **picks which team (and thus format) per scrim**.
- Q: How is a scrim agreed between two teams? → A: Support **both** — a directed **propose → accept/decline**, and an **open listing → claim**.
- Q: Does confirming a scrim set up a game server? → A: **Schedule only** for now (no auto-provisioning); getting a server stays with the separate request/approval flow.

## User Scenarios & Testing *(mandatory)*

RGL (rgl.gg) is the main competitive TF2 league; a player's RGL profile and teams are keyed by their
Steam ID — the same verified identity the user signs in with. This feature lets a signed-in user
**link their RGL account** (auto-detected from their Steam identity, no manual entry) to establish
their competitive team identity, and then lets two teams **schedule a scrimmage** together — either
by directly proposing a match to a specific opponent, or by posting an open listing another team can
claim. Confirming a scrim records the match (teams, format, time); it does **not** provision a server
(that stays with the request/approval flow).

### User Story 1 - Link my RGL account and see my team(s) (Priority: P1)

As a signed-in user, I can link my RGL account with one action and see my RGL profile name and my
current team(s) — team name, format (Sixes, Highlander, Prolander), and division/season — and I can
refresh or unlink it. This link is the prerequisite for scheduling scrims.

**Why this priority**: Scheduling is team-vs-team, so a verified team identity must exist first.
Nothing else works without it.

**Independent Test**: While signed in, choose "Link RGL account"; confirm the app shows your RGL
profile name and current team(s) without entering any RGL ID/URL; refresh and unlink work.

**Acceptance Scenarios**:

1. **Given** a signed-in user whose Steam identity has RGL team(s), **When** they link, **Then** their
   RGL profile name and current team(s) (name, format, division/season) are displayed and stored.
2. **Given** a user on multiple teams (e.g. a Sixes team and a Highlander team), **When** they link,
   **Then** all current teams are listed, grouped by format.
3. **Given** a linked user, **When** they refresh, **Then** the stored team details update to RGL's
   current values; **When** they unlink, **Then** the RGL association and details are removed.

---

### User Story 2 - Propose a scrim to a specific team (Priority: P2)

As a captain, I can propose a scrim to a specific opponent team — choosing which of my teams I'm
representing (and thus the format), the opponent, and a date/time — and the opponent's side can
accept or decline. It becomes a confirmed match only when they accept.

**Why this priority**: The primary scheduling path — directed team-to-team coordination with mutual
consent.

**Independent Test**: As team A, propose a scrim to team B for a date/time; as team B, see the
pending proposal and accept it; confirm both teams see a confirmed match; separately, decline a
proposal and confirm it closes without a match.

**Acceptance Scenarios**:

1. **Given** two RGL-linked teams of the same format, **When** captain A proposes a scrim to team B
   (team, opponent, date/time), **Then** team B sees a pending incoming proposal and A sees a pending
   outgoing one.
2. **Given** a pending proposal, **When** team B accepts, **Then** the scrim is confirmed and appears
   as an upcoming match for both teams with the agreed time and format.
3. **Given** a pending proposal, **When** team B declines (or A withdraws), **Then** no match is
   created and the proposal is closed.
4. **Given** a user, **When** they attempt to propose to a team of a **different** format, **Then**
   the system prevents it (scrims are within one format).

---

### User Story 3 - Post and claim an open scrim listing (Priority: P3)

As a captain looking for any opponent, I can post an open scrim listing (my team, format, date/time)
without naming an opponent; another eligible team can browse open listings and claim mine, which
confirms the scrim between our two teams.

**Why this priority**: The second scheduling path — useful for finding opponents when you don't have
a specific team in mind. Builds on the same match model as US2.

**Independent Test**: As team A, post an open listing for a date/time; as team B, find it in the open
listings and claim it; confirm both teams now see a confirmed match and the listing is no longer
open.

**Acceptance Scenarios**:

1. **Given** an RGL-linked team, **When** captain A posts an open listing (team, format, date/time),
   **Then** it appears in the open listings for that format.
2. **Given** an open listing, **When** captain B claims it with a same-format team, **Then** the scrim
   is confirmed between A and B and the listing is removed from the open list.
3. **Given** an open listing, **When** two teams try to claim it, **Then** the first claim wins and
   the later claimant is told it is no longer available.
4. **Given** an open listing, **When** its owner cancels it before anyone claims, **Then** it is
   removed and no match is created.

---

### Edge Cases

**Linking**
- **No RGL profile** for the Steam identity → clear "not found" message; stays unlinked.
- **Profile but no current team** → links, shows "no current team"; the user cannot schedule until on
  a team.
- **RGL unavailable / timeout** → friendly retry message; the page still works.
- **RGL status flags** (verified / banned / on probation) → surfaced as an informational badge.

**Scheduling**
- **Unlinked / no-team user** attempts to propose, accept, or claim → blocked with a message to link
  RGL / join a team first.
- **Format mismatch** (proposing to or claiming with a different-format team) → prevented.
- **Proposing to your own team** → prevented.
- **Past date/time** → rejected.
- **Simultaneous claims** of one open listing → first claim wins; others see "no longer available".
- **Cancellation** of a confirmed scrim → allowed by either team with the other notified; the match is
  marked cancelled (not silently deleted).
- **Acting for a team you're not on** → prevented (a user may only act for teams their linked RGL
  profile shows them on).

## Requirements *(mandatory)*

### Functional Requirements — RGL linking

- **FR-001**: A signed-in user MUST be able to link their RGL account from their account area with a
  single action.
- **FR-002**: The system MUST identify the user's RGL profile from their verified Steam identity — the
  user MUST NOT be required to enter an RGL ID, URL, or credentials.
- **FR-003**: On linking, the system MUST retrieve and display the user's RGL profile name and all
  current team(s), including team name, format, and division/season where available.
- **FR-004**: The system MUST persist the RGL link and retrieved team details with the user's account
  so they show on return, and MUST show link status and last-refreshed time.
- **FR-005**: The user MUST be able to refresh their RGL data on demand and to unlink (removing the
  stored association and details).
- **FR-006**: If the identity has no RGL profile or no current team, or RGL is unavailable, the system
  MUST show a clear, friendly message and MUST NOT present an error or broken page.
- **FR-007**: When RGL provides account status flags (verified / banned / on probation), the system
  SHOULD surface them as informational badges; such flags MUST NOT block linking.

### Functional Requirements — Scrim scheduling

- **FR-008**: A user MUST have a linked RGL team to take any scheduling action; being RGL-linked with
  a current team is a prerequisite to propose, accept, post, or claim a scrim.
- **FR-009**: When creating a scrim, the user MUST select which of their linked teams they are
  representing; that team's format governs the scrim.
- **FR-010**: The system MUST support a **directed proposal**: a user proposes a scrim to a specific
  opponent team with a date/time; it stays **pending** until the opponent accepts (→ **confirmed**) or
  declines (→ closed). The proposer MUST be able to withdraw a pending proposal.
- **FR-011**: The system MUST support an **open listing**: a user posts a scrim (their team, format,
  date/time) with no named opponent; another eligible team MUST be able to **claim** it, which
  **confirms** the scrim between the two teams and removes the listing. The owner MUST be able to
  cancel an unclaimed listing.
- **FR-012**: Scrims MUST be within a single format — a team may only propose to, or claim/accept a
  scrim with, a team of the **same** format.
- **FR-013**: A confirmed scrim MUST record the two teams, the format, the agreed date/time, and a
  status (pending / confirmed / declined / cancelled / open / claimed).
- **FR-014**: A user MUST be able to view their scrims for each of their teams — incoming and outgoing
  pending proposals, confirmed/upcoming matches, and their own open listings — and MUST be able to
  browse open listings for a format.
- **FR-015**: Either team MUST be able to cancel a confirmed scrim, marking it cancelled (not deleting
  it) so the other team can see the change.
- **FR-016**: A user MUST only be able to act for a team their linked RGL profile shows them on
  (propose/accept/claim/cancel) — never on behalf of a team they are not on.
- **FR-017**: The system MUST reject invalid scrims: a date/time in the past, proposing to one's own
  team, or claiming an already-claimed/cancelled listing.
- **FR-018**: Confirming a scrim MUST NOT provision, reserve, or attach a game server; getting a
  server stays with the separate request/approval flow (a scrim MAY reference a server later).

### Key Entities *(include if feature involves data)*

- **RGL link**: association between a user account and its RGL profile. Attributes: owner Steam
  identity (one per account), RGL profile name, link state (linked / no-profile / no-team), status
  flags (verified/banned/probation, if provided), linked-at, last-refreshed-at.
- **RGL team (current)**: a team the user is currently on per RGL. Attributes: RGL team id, name, tag,
  format (Sixes / Highlander / Prolander), division/tier, season. A user may have several (one per
  format). Teams are the actors that scrims are scheduled between.
- **Scrim (match)**: a scheduled scrimmage between two teams. Attributes: format, requested date/time,
  proposing team, opponent team (empty while an open listing is unclaimed), origin (directed proposal
  or open listing), status (pending / confirmed / declined / cancelled / open / claimed), created-by
  user, created-at. Directed proposals start **pending**; open listings start **open** and become
  **confirmed** on claim.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A signed-in user can link their RGL account and see their team(s) in a single action,
  with no manual ID/URL entry, in under ~10 seconds.
- **SC-002**: For a user with an RGL team, the displayed profile name and team(s) match their RGL
  profile; a linked association persists across sessions and can be refreshed/unlinked.
- **SC-003**: A captain can propose a scrim and the opponent can accept, producing a confirmed match
  visible to both teams with the agreed time and format, in under ~2 minutes.
- **SC-004**: Both scheduling paths (directed propose→accept and open listing→claim) result in a
  confirmed scrim that records both teams, the format, and the date/time.
- **SC-005**: 100% of created/claimed/accepted scrims are same-format; cross-format scheduling is
  never possible.
- **SC-006**: A user can only act for teams their linked RGL profile shows them on — never another
  team (0% cross-team actions).
- **SC-007**: Confirming a scrim never triggers server provisioning (0 servers created by scheduling).
- **SC-008**: A user with no RGL profile / no team, or when RGL is unavailable, always sees a clear
  message and never an error or broken page.

## Assumptions

- **Auto-detected from Steam identity**: RGL profiles/teams are keyed by Steam ID and the user is
  signed in with that verified identity, so linking is automatic (the example RGL URL's `p=<steamid>`
  equals the signed-in identity). No RGL login/credentials; RGL data is read from RGL's public info.
- **Current teams, snapshot + refresh**: the feature shows current team(s) per format; a snapshot is
  stored at link time and updated on refresh (a last-refreshed indicator is shown). History is out of
  scope.
- **Team representation**: a user may act for any team their linked RGL profile lists them on; there is
  no separate captain-only restriction in this phase (small trusted competitive scene). Roster-based
  authority may be tightened later.
- **Directed proposals target teams present on the platform**: to receive/accept a proposal, the
  opponent team must have at least one RGL-linked member on the platform; open listings cover finding
  opponents more broadly within a format.
- **Schedule-only**: confirming a scrim records the match (teams, format, time) but does not touch
  servers, payment, or provisioning (Constitution Principle VIII — access is via request/approval). A
  scrim may reference a server in a later feature.
- **Date/time handling**: scrim times are stored unambiguously and shown in the user's local time;
  exact timezone presentation is a planning detail.
- **Depends on sign-in (feature 002)**: the RGL link and scrims attach to the existing user account
  and its owner-only, session-guarded areas.
- **One RGL profile per account**: both keyed by the same Steam ID, so an account maps to at most one
  RGL profile.

## Dependencies

- **Feature 002 (Sign in with Steam)** — provides the verified Steam identity, user account, and
  owner-only/session context.
- **RGL public data** — availability of RGL's public profile/team information for a Steam ID.
