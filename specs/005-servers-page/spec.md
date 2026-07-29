# Feature Specification: The Servers Page

**Feature Branch**: `005-servers-page`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "The Servers page I would like this feature to discribe how the page looks and functions."

## Context

The Servers page exists today only as a walking-skeleton placeholder from `001-basic-flask-app`: a
table of hard-coded sample servers, a "+ Create server" form that validates and discards, a settings
form that never saves, and a console that echoes a canned reply. Feature `004` added access control,
so a viewer now sees only servers they own or that belong to an RGL team they are on.

Since then the product has been redefined (constitution v3.0.0): **scheduling is free, and servers
are the paid upsell that attaches to a scrim a team has already scheduled.** A server is never
self-created — it exists only because the operator handled payment out-of-band and recorded an
approval. The page's current centrepiece, a self-service "+ Create server" button, therefore
describes a product that no longer exists and offers an action no user can complete.

This feature defines what the Servers page **is**: the place where a team sees the servers it is
entitled to, asks for one for a scrim, and manages the ones it has.

### Scope of this increment

The **payment, request, and approval loop is real and persisted**; the **servers themselves are
still simulated**. A team genuinely pays, genuinely requests, and the operator genuinely approves —
and an approved request produces a server entry whose lifecycle state is represented but not backed
by real compute. Cluster provisioning (public UDP exposure, administrative control, auto-start and
teardown timed to a match) remains the next feature's risk, per the constitution's build order.

Requirements below are tagged **[sim]** where they are satisfied by simulated server state this
increment and only become fully real once provisioning lands.

## Clarifications

### Session 2026-07-29

- Q: Does this feature include real provisioning, or the page's look and behaviour with provisioning
  still simulated? → A: Payment, request and approval are real and persisted; server provisioning
  stays simulated (option A).
- Q: How does a sent payment become an approved entitlement? → A: The platform observes the
  operator's received trade offers through Steam's API, attributes each to a user account, and
  credits the entitlement automatically once the offer is accepted (option B). The operator still
  accepts trades on Steam by hand; no Steam API exists to accept on their behalf.
- Q: What constitutes sufficient payment? → A: Mann Co. Supply Crate Keys (Team Fortress 2, app 440).
  No other item counts toward the requirement; minimum accepted payment is 2 keys.
- Q: What does payment buy? → A: **Credits**, which are units of server runtime. 2 keys grant 5
  credits; 1 credit runs a server for 1 hour; extending a running server by 30 minutes costs 1 credit.
- Q: A user whose trade would be held in escrow → A: Blocked from paying until Steam Guard Mobile is
  enabled. Recorded as a default after the question was twice deferred; revisit if warn-and-allow is
  preferred.
- Q: What happens when a server's runtime window runs out? → A: A 15-minute unpaid grace period, then a
  hard stop unless the window has been extended — matches often run slightly past their allotted time.
  The grace is granted once per server, not per extension.
- Q: Does the operator need an in-app approve/decline queue? → A: No. Crediting is automatic on the
  trade being accepted, so there is no manual approval step to house. A read-only operator view of
  payments and servers may be worth a later feature.
- Q: When does a server's runtime window start? → A: At the scrim's **scheduled time**, with the server
  ready to join by then. Not at first player connection, and not when provisioning finishes — getting
  ready is not charged, but a late team loses its own time.
- Q: Where can credits be spent on a server? → A: When proposing a scrim, when posting a listing, when
  **claiming** a listing, and afterwards from the Servers page. Extending is available from the scrim's
  own page as well as the Servers page.
- Q: What is shown to a user with no credits? → A: No credit-spending action at all — not a disabled
  one, not one that fails on submit. The route to buying credits is shown in its place.

### Session 2026-07-29 (post-implementation, from `/speckit-analyze`)

- Q: Is a payment visible to the payer's whole team, or only to the payer? → A: **Only the payer.**
  FR-018 amended. The original team-visible wording conflicted with FR-070 and FR-047, and the thing a
  team needs is the server, not its captain's payment record.
- Q: Does a cancelled or past target scrim invalidate the payment it was started for? → A: **No.**
  Credits are fungible and not scrim-bound, so the payment completes and the credits land; only the
  link to that scrim is reported as no longer applicable. FR-020 clarified accordingly.
- Q: Where does a user ask for a server? → A: Primarily while scheduling — the propose-a-scrim and
  post-a-listing forms each offer to have a server started when the scrim begins. The Servers page
  remains a second path for attaching one to an already-scheduled scrim. Scheduling itself is never
  blocked by payment.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - See the servers I actually have, and their live state (Priority: P1)

As a captain who has been granted one or more servers, I open the Servers page and immediately see
each server I am entitled to: what it is called, whether it is up, how many players are on it, the
address and join password needed to get my team into it, and — for a per-scrim server — which scrim
it belongs to and when it goes away. Servers belonging to other teams are absent entirely.

**Why this priority**: This is the page's reason to exist and the thing a paying team needs on a
Sunday evening five minutes before a match. It stands alone: even with no request flow and no
management controls, a team that can find and join the server it paid for has received the value.

**Independent Test**: Grant a viewer access to one running and one stopped server, open the page, and
confirm both render with state and connect details, that a third server bound to another team is not
listed, and that the page is reachable from the main navigation.

**Acceptance Scenarios**:

1. **Given** I have a running server, **When** I open the Servers page, **Then** I see it listed as
   running with its player count, map, address and join password, so I can connect without asking
   anyone.
2. **Given** I have a server that is not running, **When** I view it, **Then** its state is shown
   plainly along with why it is not running — not yet started, ended, suspended, or expired — rather
   than as an empty or ambiguous row.
3. **Given** a server is bound to a scrim, **When** I view it, **Then** it names that scrim and its
   scheduled time, and states when the server will be reclaimed.
4. **Given** a server belongs to a team I am not on, **When** I open the Servers page, **Then** it
   does not appear; **When** I address it directly, **Then** the response is indistinguishable from a
   server that does not exist.
5. **Given** I have no servers, **When** I open the page, **Then** I get an empty state that says
   scheduling is free, explains that servers are requested for a scrim and approved by the operator,
   and offers the request action — not a dead "create" button.

---

### User Story 2 - Get a server for a scrim, ideally as I schedule it (Priority: P2)

As a captain arranging a match, I can ask for a server **at the moment I schedule it** — a choice on
the propose-a-scrim and post-a-listing forms to have a server ready when the scrim starts — so that
arranging the match and arranging somewhere to play it are one action. If I didn't tick it then, or I
arranged the scrim before I had paid, I can still attach a server later from the Servers page. Either
way the state of that server and of my payment is visible to me without messaging the operator.

**Why this priority**: This is the revenue entry point and the moment the free product becomes a paid
one. It depends on Story 1's inventory view existing to show the result, so it follows.

**Independent Test**: With an upcoming confirmed scrim and no server, submit a request from the
Servers page and confirm it appears as pending to the whole team, with no out-of-band message needed
to learn its status.

**Acceptance Scenarios**:

1. **Given** I have an upcoming scrim with no server, **When** I open the Servers page, **Then** that
   scrim is surfaced as something I can request a server for.
2. **Given** I request a server for a scrim, **When** the request is submitted, **Then** it appears on
   the page as awaiting operator approval, naming the scrim it is for and when I asked.
3. **Given** I have a pending request, **When** I try to request another server for the same scrim,
   **Then** the page prevents the duplicate and points me at the existing request.
4. **Given** the operator approves my request, **When** I next open the page, **Then** the request has
   become a server entry showing when it will be ready relative to the scrim's start.
5. **Given** the operator declines my request, **When** I open the page, **Then** I see it was
   declined, and the scrim is again something I can request a server for.
6. **Given** the scrim a pending request is for is cancelled, **When** I open the page, **Then** the
   request is shown as no longer applicable rather than waiting forever on a match that will not
   happen.
7. **Given** I am not linked to an RGL team, **When** I open the page, **Then** I am prompted to link
   my RGL account instead of being offered a request I cannot make.
8. **Given** I am proposing a scrim, **When** I choose to have a server started for it and I hold an
   entitlement, **Then** the scrim is created with a server attached to it, and both the scrim and the
   Servers page show that attachment.
9. **Given** I am posting an open listing, **When** I choose to have a server started for it, **Then**
   the same choice is available and behaves identically.
10. **Given** I choose to have a server started but hold no entitlement, **When** I submit the form,
    **Then** the scrim is still created — scheduling is free and MUST NOT be blocked — and I am taken
    to payment with that scrim remembered as what the server is for.
11. **Given** I ticked the option and never completed payment, **When** the scrim's start approaches,
    **Then** the scrim shows plainly that no server is attached, rather than implying one is coming.
12. **Given** I attached a server to an open listing that nobody ever claims, **When** the listing
    lapses or I cancel it, **Then** my entitlement is released rather than consumed.

---

### User Story 3 - Manage and control a server I have (Priority: P3)

As the captain who owns a granted server, I can change what is changeable about it — its name, its
map, its join password, its capacity — and I can issue administrative commands to it while it is
running, from the same page I found it on.

**Why this priority**: Real value, but a team can play a scrim on a correctly provisioned server
without ever touching these. Deferring it keeps the first increment small, per Principle I.

**Independent Test**: Open a running server owned by the viewer, change its settings and confirm the
change is applied and reflected, then issue a command and confirm the server's real response appears.

**Acceptance Scenarios**:

1. **Given** I own a running server, **When** I change its map or join password, **Then** the change
   is applied to the running server and the page reflects the new values.
2. **Given** I submit settings that are not valid, **When** the form is submitted, **Then** the
   offending fields are flagged individually and nothing is applied.
3. **Given** I own a running server, **When** I issue an administrative command, **Then** the server's
   actual response is shown to me.
4. **Given** a server is not running, **When** I view it, **Then** commands are unavailable with the
   reason stated, rather than failing obscurely.
5. **Given** a server is bound to a scrim rather than rented for a season, **When** I view it, **Then**
   only the settings meaningful for a short-lived match server are offered.
6. **Given** a viewer is on the server's team but does not own it, **When** they view it, **Then** they
   can see and join it, and the page makes clear which controls belong to the owner.

---

### User Story 4 - Understand a term ending, or a server that could not be placed (Priority: P4)

As a captain with a season-long rented server, I can see how much of my term is left and what happens
when it ends. And if the platform could not give me a server for a scrim it promised one for, I find
that out from this page in time to arrange somewhere else to play.

**Why this priority**: Prevents the two worst surprises — a server vanishing unannounced, and turning
up to a match with nothing to play on. Both are only reachable once servers exist, so this sits last.

**Independent Test**: View a server whose term is near its end and confirm the remaining term and the
end-of-term consequence are stated; separately, mark a server as having failed to be placed and
confirm its team sees that failure.

**Acceptance Scenarios**:

1. **Given** I rent a server for a season, **When** I view it, **Then** I see when the term ends and
   what happens at that point.
2. **Given** my term has ended, **When** I view the server, **Then** I see it is suspended, that its
   configuration and maps are retained for a stated period, and how to renew.
3. **Given** the grace period has passed, **When** I open the page, **Then** the server is no longer
   listed as mine.
4. **Given** a server for one of my scrims could not be placed, **When** I open the page, **Then** the
   failure is stated plainly against that scrim rather than the server simply being absent.

---

### User Story 5 - Buy credits, and buy more time mid-match (Priority: P2)

As a captain, I can turn keys into credits by trading with the operator, see my balance and where every
credit went, and — when a scrim overruns — buy another 30 minutes without leaving the match. This
should be built alongside Story 2: a request for a server is meaningless until credits exist to pay for
one.

**Why this priority**: This is the increment's whole reason for being — the loop that turns a free user
into a paying one — and the extension is the moment the product either saves a match or ruins it.

**Independent Test**: With a free account, complete a trade, confirm the balance rises by the expected
credits and the ledger explains it; then, on a running server, extend it and confirm the time remaining
grows and the balance falls by one.

**Acceptance Scenarios**:

1. **Given** I am a new user with no credits, **When** I open the Servers page, **Then** I see my
   balance is zero, what a server costs, and the action to pay.
2. **Given** I start the payment action, **When** it opens, **Then** a trade offer to the operator is
   started for me, and the page tells me exactly what to put in it.
3. **Given** I have not enabled Steam Guard Mobile, **When** I try to pay, **Then** I am told why I
   cannot yet and what to do about it — no trade is started.
4. **Given** I send 2 keys and the operator accepts, **When** I return to the page, **Then** my balance
   is 5 credits and the ledger records the payment that created them.
5. **Given** I send items that are not keys, **When** the offer is seen, **Then** my payment is marked
   insufficient with the reason, and no credits are granted.
6. **Given** my server has 10 minutes left, **When** I extend it, **Then** it gains 30 minutes and my
   balance falls by 1, and both are reflected immediately.
7. **Given** my server has time left but my balance is zero, **When** I try to extend, **Then** I am
   told my balance is zero and offered the way to buy more.
8. **Given** I want to check where my credits went, **When** I look at my ledger, **Then** every grant,
   reservation, extension and return is listed with its cause.
9. **Given** my server's hour has just run out mid-match, **When** the window ends, **Then** the server
   keeps running, I am told I am in the 15-minute grace and how long is left, and no credit is taken.
10. **Given** I am in the grace period, **When** I extend, **Then** players notice nothing — the server
    never stops — and my balance falls by 1.
11. **Given** I am in the grace period and do not extend, **When** the 15 minutes elapse, **Then** the
    server stops and my team can see it stopped because the time ran out.
12. **Given** I have already used my grace on this server, **When** a later window ends, **Then** there
    is no second grace and the server stops unless I have extended.
13. **Given** I have zero credits, **When** I view a scrim, a listing, or the Servers page, **Then** no
    credit-spending action is offered anywhere — instead I am shown how to buy credits.
14. **Given** I am claiming someone else's open listing, **When** I claim it, **Then** I can choose to
    spend credits on a server for that scrim as part of claiming it.
15. **Given** a scrim of mine is under way, **When** I open the scrim's own page, **Then** I can extend
    its server from there, and I am told the cost and the time it adds before I commit.
16. *(Deferred with FR-082 — there is no reschedule flow to exercise.)* **Given** a scrim is
    rescheduled after I reserved credits for it, **When** the new time arrives, **Then** the server is
    ready then instead, and no credits were lost or double-spent.

---

### Edge Cases

- A signed-in user with **no linked RGL account** — sees the link prompt, not an inventory or a
  request form.
- A linked user **on no team** — cannot request (a server binds to a team), and is told why.
- A user on **several teams** — the page makes clear which team each server and request belongs to.
- A request whose scrim is **cancelled, declined, or already past** while the request is still pending.
- A scrim whose **opponent later withdraws**, leaving a once-confirmed match unconfirmed.
- **Two captains on the same team** both requesting a server for the same scrim.
- A per-scrim server viewed **before** its start window, **during** the match, and **after** teardown.
- A season server viewed while **suspended**, **in grace**, and **after reclamation**.
- The platform is at its **concurrent-server cap** when a request is approved (Principle VII: this
  must fail visibly to the team, not silently degrade the cluster).
- The cluster is **unreachable**, so live state cannot be determined — the page must distinguish
  "stopped" from "unknown".
- A server has a **join password** — it must reach the team without ever exposing the administrative
  password (Principle IV).
- Legacy **sample/demo servers** remain visible and must stay unmistakably labelled as not real.
- A scrim scheduled **with the server option ticked but payment never completed** — the scrim must
  stand on its own and say plainly that no server is attached.
- An **open listing with a server attached that nobody claims**, or that the poster cancels.
- A scrim with a server attached that is **cancelled or declined** before the server starts.
- A user attempting to **reserve one entitlement against two scrims**.
- Payment that **completes after the scrim has already started**, or after it has finished.
- A trade arriving from someone with **no account on the platform**, or attributable to no request.
- **Overpayment** — more keys sent than the minimum; converts to more credits.
- A server's **hour running out mid-round**, and an extension bought with seconds to spare.
- A server whose **grace period elapses** with nobody watching the page.
- A server that has **already spent its one grace** and reaches a second window end.
- An extension bought **during** the grace, and one bought **after** the server has already stopped.
- An **extension attempted with an empty balance** during a live match.
- Two scrims scheduled **close enough together** that one server's window overlaps the next.
- A scrim that **starts late**, so the window would end before the match does.
- **Credits reserved for a scrim that is rescheduled** to a different time.
- A payment that **completes while a scrim is already under way**, or after it ended.
- A balance a user **disputes** — the ledger must explain every movement without operator help.
- Steam's trade API **unreachable** while a payment is in flight; the free scrim surface must be
  wholly unaffected.

## Requirements *(mandatory)*

### Functional Requirements

**Access and visibility**

- **FR-001**: The page MUST show only servers the viewer owns or that are bound to an RGL team the
  viewer belongs to, re-checked against stored memberships on every request.
- **FR-002**: A server the viewer may not access MUST be indistinguishable from one that does not
  exist.
- **FR-003**: The page MUST require a signed-in, Steam-verified identity.
- **FR-004**: A viewer with no linked RGL account MUST be prompted to link it rather than shown an
  inventory or a request form.

**Inventory and state**

- **FR-005**: Each server MUST display its name, current state, map, player count against capacity,
  and the team it belongs to.
- **FR-006**: Each server MUST display a distinct state covering at least: awaiting approval,
  approved but not yet started, starting, running, ended, failed to start, suspended, in grace, and
  reclaimed.
- **FR-007** *[sim]*: When live state cannot be determined, the page MUST say so rather than
  reporting the server as stopped.
- **FR-008** *[sim]*: For a running server, the page MUST display everything the viewer's team needs
  to connect — address, and join password if one is set.
- **FR-009**: The page MUST NEVER display the administrative (RCON) password to any viewer.
- **FR-010**: A server bound to a scrim MUST name that scrim, its scheduled time, and when the server
  will be reclaimed.
- **FR-011**: A season-term server MUST show its term end and the consequence of that term ending.
- **FR-012**: The page MUST show an empty state that says scheduling is free, explains that servers
  are requested and operator-approved, and offers the request action.
- **FR-013**: Servers that are placeholder sample data MUST be labelled as not real.

**Requesting**

- **FR-014**: The page MUST NOT offer self-service server creation. Every server MUST originate in an
  entitlement the operator granted, and the operator's acceptance of the payment is that granting
  act.
- **FR-015**: Users MUST be able to request a server for a specific scrim their team has scheduled.
- **FR-016**: The page MUST surface the viewer's upcoming scrims that have neither a server nor a
  pending request as candidates for a request.
- **FR-017**: The platform MUST reject a second request for a scrim that already has a pending or
  approved one, and point the requester at the existing request.
- **FR-018**: A submitted payment MUST be visible to **the account that made it**, with its state,
  the scrim it was for, and when. It MUST NOT be shown to other members of that account's teams.
  *Amended after implementation:* the original wording made payments team-visible, which contradicted
  FR-070 (credits belong to the paying account) and FR-047 (a trade link is visible only to its owner
  and the operator). A payment is a personal financial act; what the team actually needs to see is the
  **server** it produces, and FR-001 already makes that team-visible.
- **FR-019**: A request MUST display its current state — awaiting payment, payment held, entitled and
  scheduled, or failed with the reason — without the requester contacting the operator.
- **FR-020**: A payment whose target scrim has been cancelled, declined, or already passed MUST be
  shown as no longer applicable to that scrim. The **payment itself remains valid** — credits are not
  bound to a scrim, so a stale target costs the payer nothing, and they MUST be told the credits can
  be spent on something else.
- **FR-021**: The platform MUST NOT collect, process, or store card or bank details anywhere, and MUST
  NOT move money itself; payment is completed on the payment provider's own surface — for the first
  method, Steam. A user's trade link is an account identifier, not a financial instrument, and storing
  it does not breach this.
- **FR-022**: Approval MUST be enforced server-side and never inferred from anything the client
  submits.

**Management**

- **FR-023** *[sim]*: A server's owner MUST be able to change its name, map, join password, and
  capacity within valid bounds, and the change MUST be applied to the running server.
- **FR-024**: Invalid settings MUST be rejected per-field with nothing applied.
- **FR-025** *[sim]*: A server's owner MUST be able to issue administrative commands to a running
  server and see the server's actual response.
- **FR-026** *[sim]*: Administrative commands MUST be unavailable, with the reason stated, when the
  server is not running.
- **FR-027**: The page MUST distinguish controls available to the server's owner from those available
  to other members of its team.
- **FR-028**: A per-scrim server MUST offer only the settings meaningful for a short-lived match
  server.

**Accounts and payment** *(first method: Steam trade offer; more methods are planned — see
Assumptions)*

- **FR-031**: A user who signs in with Steam MUST get a **free account by default**, holding no
  entitlement, and that free account MUST grant the complete scrim surface at no charge.
- **FR-032**: The Servers page MUST offer a user without an entitlement a payment action that opens a
  trade offer to the operator on Steam.
- **FR-033**: The page MUST state what the user is expected to send before they start the trade, and
  what it will buy them — naming the item and the quantity explicitly.
- **FR-034**: The operator's trade destination and the platform's Steam API credential MUST come from
  managed configuration held in the platform's secret store. Neither may be committed to the repository
  or appear in source.
- **FR-035**: The Steam API credential MUST NEVER be logged, and MUST NEVER be delivered to any
  client.
- **FR-036**: The platform MUST observe trade offers received by the operator and attribute each to a
  user account by the offer's partner account identifier, mapped to that user's Steam identity.
- **FR-037**: Attribution and crediting MUST derive solely from what Steam reports; neither may rely
  on anything the client submits.
- **FR-038**: The platform MUST credit an entitlement only once a trade offer has reached the accepted
  state.
- **FR-039**: The platform MUST determine whether a received offer's contents meet the required
  payment, using configured item and quantity rules, and MUST leave the payment incomplete when they
  do not — stating why.
- **FR-040**: A trade offer held in Steam's escrow MUST be shown to the payer as held, with the date
  the hold ends, and MUST NOT credit an entitlement until it completes.
- **FR-041**: Before offering the payment action, the platform MUST check whether a trade from this
  user would be held, and MUST act on the result per the escrow policy in FR-042.
- **FR-042**: A user whose trade would be held MUST be blocked from paying, and told plainly that
  Steam Guard Mobile Authenticator must be enabled for the qualifying period first. No payment that
  cannot complete in time may be accepted.
- **FR-043**: A trade that is cancelled, declined, or expired MUST leave the payment incomplete and
  the reason visible to the payer.
- **FR-044**: Users MUST be able to record their own Steam trade link on the Accounts page, beneath
  RGL linking, and MUST be able to change it.
- **FR-045**: The platform MUST tell the user why their trade link is wanted — it is what allows the
  escrow pre-check of FR-041 and any return of items.
- **FR-046**: A malformed trade link MUST be rejected with the specific problem stated, and MUST NOT
  be stored.
- **FR-047**: A user's trade link MUST be visible only to that user and the operator.
- **FR-048**: Adding a further payment method MUST NOT require changing the entitlement, request, or
  approval model.
- **FR-049**: The only accepted item MUST be the **Mann Co. Supply Crate Key** (Team Fortress 2, app
  440). Anything else MUST NOT count toward payment, including similarly-named keys from other games.
- **FR-050**: An offer of fewer than the minimum accepted payment MUST be treated as insufficient, and
  the payer MUST be told what arrived against what is needed.
- **FR-051**: The accepted item, the minimum payment, and the credits granted per key MUST be
  configurable without a code change, so the price can move with the market.

**Attaching a server while scheduling**

- **FR-052**: The propose-a-scrim form, the post-a-listing form, and the **claim-a-listing** action MUST
  each offer the option to spend credits on a server for that scrim, started for when it begins.
- **FR-053**: Choosing that option with a sufficient credit balance MUST attach a server to the scrim
  on creation and reserve the credit for its first hour.
- **FR-054**: Choosing that option without sufficient credits MUST still create the scrim, then take
  the user to payment with the scrim retained as the server's intended target. Scheduling MUST NEVER be
  blocked, delayed, or made to fail by anything to do with payment or credit balance.
- **FR-055**: A scrim with a server attached MUST show that fact wherever the scrim is shown; a scrim
  where the option was chosen but payment never completed MUST show that no server is attached rather
  than implying one is pending.
- **FR-056**: Credits reserved against an open listing MUST be returned to the balance, not spent, if
  the listing is cancelled or lapses unclaimed.
- **FR-057**: Cancelling or declining a scrim with a server attached MUST return its reserved credits
  if the server has not yet started.
- **FR-058**: The same credit MUST NOT be reservable against two scrims.

**Credits and server runtime**

- **FR-059**: An account MUST hold a credit balance, shown on both the Servers page and the Accounts
  page.
- **FR-060**: 1 credit MUST entitle a server to run for **1 hour**.
- **FR-061**: Attaching a server to a scrim MUST reserve 1 credit for its first hour.
- **FR-062**: A running server MUST show how much of its allotted time remains.
- **FR-063**: A server's owner MUST be able to extend a running server by **30 minutes** at a cost of
  **1 credit**.
- **FR-064**: Extension MUST be repeatable for as long as credits remain.
- **FR-065**: Any action that spends credits — attaching a server, claiming with a server, extending —
  MUST NOT be offered to a user whose balance cannot cover it. In its place the page MUST show the route
  to buying credits, so the absence of the action is never unexplained.
- **FR-066**: The platform MUST warn the owner that time is running out before it does, early enough
  to act, and again when the grace period of FR-072 begins.
- **FR-067**: Credits MUST NOT be spent for time a server did not get. A server that never started, or
  that failed, MUST return its reserved credits.
- **FR-068**: Every change to a credit balance MUST be recorded with its cause — payment, reservation,
  extension, return, or expiry — and be visible to the account holder, so a disputed balance can be
  explained without the operator's help.
- **FR-069**: Credits MUST NOT expire.
- **FR-070**: A credit balance MUST belong to the account that paid, and MUST NOT be spendable by other
  members of that account's teams.
- **FR-071**: The page MUST state the price and the conversion rate — what a key buys, what a credit
  buys, and what an extension costs — before a user pays.
- **FR-072**: When a server's runtime window runs out, the platform MUST allow it to keep running for a
  **15-minute unpaid grace period**, then stop it unless the window has been extended. Matches commonly
  run slightly long; the grace covers that without a mid-round stop.
- **FR-073**: The grace period MUST cost no credits and MUST leave the server fully usable.
- **FR-074**: The grace MUST be granted **once per server**, not once per window or per extension, so
  that repeated extension cannot be used to accumulate free time.
- **FR-075**: During the grace the owner MUST be told, prominently, that the server is on borrowed time,
  how long is left, and how to extend.
- **FR-076**: At the end of the grace, an un-extended server MUST stop, and its team MUST be able to see
  that it stopped because time ran out rather than because something broke.
- **FR-077**: Extending at any point before the grace ends MUST keep the server running continuously,
  with no interruption to players.
- **FR-078**: A server's runtime window MUST begin at its scrim's **scheduled start time**, and the
  server MUST be ready to join at that moment. Credits are consumed from the scheduled time onward
  whether or not anyone has connected.
- **FR-079**: Provisioning MUST therefore begin early enough that the server is joinable by the
  scheduled time, and the time spent getting it ready MUST NOT be charged to the team.
- **FR-080**: A scrim's own page MUST offer the extend action for the server attached to it, so a team
  can buy more time from the page they are already watching during a match.
- **FR-081**: The extend action MUST show what it will cost and how much time it will add before it is
  taken.
- **FR-082** *[deferred]*: A scrim whose scheduled time is changed after credits were reserved MUST
  move its runtime window with it, without consuming or returning credits.
  *Deferred after implementation:* **the platform has no reschedule flow** — a scrim's time cannot be
  changed once set, only cancelled and re-created — so this requirement describes behaviour for a
  capability that does not exist and cannot be tested. It also understates the problem: whoever adds
  rescheduling must decide whether a moved scrim re-reserves its credit, and what happens when its
  server has already run. This requirement is a placeholder for that design, not a description of it,
  and MUST be re-specified alongside rescheduling itself.

**Failure**

- **FR-029** *[sim]*: A server that could not be placed MUST be reported as failed to its team,
  against the scrim it was for.
- **FR-030** *[sim]*: Reaching the platform's concurrency cap MUST surface as a visible failure to
  the affected team, never as a silently missing server.

### Key Entities

- **Server**: A dedicated game server a team is entitled to. Has a name, a lifecycle state, a map, a
  capacity and current player count, connect details, an owning captain, a bound team, and either a
  scrim binding or a term.
- **Server request**: A team's ask for a server, awaiting an operator decision. References the scrim
  it is for, who asked, when, and its outcome.
- **Credit**: One hour of server runtime, and the unit of entitlement. Held as a balance on an account,
  reserved when a server is attached to a scrim, spent as time is used, returned when a server never
  ran. The sole basis on which a server may run.
- **Credit ledger entry**: One recorded change to a balance, with its cause and the payment, scrim, or
  server it relates to. What makes a balance explainable.
- **Runtime window**: The period a server is entitled to run for — one hour per reserved credit, plus
  30 minutes per extension.
- **Scrim binding**: The link between a per-scrim server and the match it exists for, determining when
  it starts and when it is reclaimed.
- **Term**: For a rented server, the period it is owned for, plus the grace period after it lapses.
- **Account**: A Steam-verified identity. Free by default and holding no entitlement; the free state
  grants the whole scrim surface. Optionally carries a linked RGL identity and the user's own trade
  link.
- **Payment**: An attempt by a user to pay the operator through one of the supported methods. Has a
  method, the user it is attributed to, a state (started, held, complete, insufficient, failed), and
  the entitlement it produced on completion. For the trade method it corresponds to one Steam trade
  offer and carries that offer's identifier and hold-expiry, if held.
- **Payment requirement**: The configured expectation for what constitutes sufficient payment — for
  the trade method, which items and how many.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A captain can tell which of their upcoming scrims do and do not have a server within 10
  seconds of opening the page, without navigating elsewhere.
- **SC-002**: A captain can go from opening the page to a submitted server request in under 60 seconds
  and no more than three interactions.
- **SC-003**: In 100% of cases, a server belonging to a team the viewer is not on is absent from the
  page and unreachable by direct address.
- **SC-004**: 100% of listed servers display a state, and every running one displays complete connect
  details; no server renders in an unexplained or blank state.
- **SC-005**: A team can determine the status of a server request without contacting the operator in
  100% of cases, eliminating "where is my server" enquiries.
- **SC-006**: A server that fails to be placed is visible as failed to its team no later than 15
  minutes before its scrim's scheduled start.
- **SC-007**: A rented server's owner can state, from the page alone, when their term ends and what
  happens next.
- **SC-008**: A first-time visitor with no servers can correctly describe, after reading the empty
  state, that scheduling is free and that a server must be requested and approved.
- **SC-009**: The administrative password is absent from everything the page delivers to any viewer.
- **SC-010**: A team whose server is about to run out of time can buy an extension in under 15 seconds
  and no more than two interactions, without leaving the page they are on.
- **SC-011**: A user can account for every credit they have ever been granted or spent from the ledger
  alone, with no operator involvement.
- **SC-012**: A user knows the full price — keys per credit, minutes per credit, cost to extend —
  before they send anything.
- **SC-013**: No user ever sends a payment that cannot complete in time to be useful.
- **SC-014**: Scheduling a scrim succeeds 100% of the time regardless of credit balance, payment state,
  or whether the payment provider's systems are reachable.

## Assumptions

- **Requests are per-scrim, initiated by a team member.** Consistent with Principle I (paid work
  attaches to an existing scrim), the primary request path binds to a scrim already on the calendar.
  Season-long rentals are visible and manageable here, but their purchase path is arranged with the
  operator directly.
- **Any member of the owning RGL team may see and join** a server; the **captain who was granted it
  owns** it and holds the settings and administrative controls. This matches the existing access rule
  and Principle VIII's "individual (captain) ownership".
- **Payment stays entirely out-of-band.** The page explains how to pay the operator and reflects the
  approval that results; it never takes money.
- **Payment methods are plural by design.** More methods are planned beyond the first one, so
  requirements are written against "a payment method" rather than any single mechanism. Adding a
  second method MUST NOT require reworking the entitlement, request, or approval model.
- **The existing "+ Create server" entry points are removed**, including the one in the main
  navigation and the one in the dashboard's Servers box, because no user can complete that action.
- **Live state is best-effort.** Player counts and up/down are read from the cluster when reachable
  and reported as unknown when not, rather than blocking the page.
- **Notifications are out of scope** (a constitution non-goal). The page is pull-only: a team learns
  of an approval or a failure by opening it.
- **Times follow the existing convention** — rendered in the viewer's local timezone with a UTC
  fallback, as established in the previous feature.
- **Sample/demo servers persist** through this feature so the page has something to render before real
  provisioning exists, and stay explicitly labelled.
- **A server serves exactly one team.** Shared or opponent-visible servers are not modelled; the
  opposing team receives connect details out-of-band.
- **The operator accepts trades by hand.** No Steam API permits accepting a trade offer on the
  operator's behalf — it requires their own confirmation. The platform only observes offers and reacts
  to their state, so payment completes on the operator's schedule, not instantly.
- **Steam's trade API becomes load-bearing.** Payment cannot complete while Steam's API is
  unreachable or the credential is invalid. Payment states must therefore degrade honestly (a payment
  stays "started" rather than being reported failed) and the scrim surface MUST remain fully usable
  regardless, since it is free.
- **Item pricing is configured, not computed.** The platform holds a configured rule for what
  constitutes sufficient payment rather than valuing arbitrary Steam inventory; unpriceable items are
  treated as insufficient.
- **A user's trade link is optional** until they want to pay, at which point the escrow pre-check
  needs it.
- **Extensions are priced at double rate, as specified**: a credit buys 60 minutes up front but only
  30 on an extension. Recorded as intended; worth confirming it was not a slip.
- **Credits convert as `floor(keys × credits-per-key)`**, with credits-per-key initially 2.5 so that 2
  keys grant 5. This avoids holding fractional remainders: 4 keys grant 10, 3 keys grant 7. The
  minimum accepted payment is 2 keys.
- **Credits are account-level, not team-level**, per Principle VIII's individual captain ownership. A
  captain's credits are not spendable by teammates, though the server those credits produce is visible
  and joinable by the whole team.
- **The runtime window starts at the scrim's scheduled time.** The server must be ready to join at that
  moment, so provisioning begins early enough to be up beforehand, and credits are consumed from the
  scheduled time onward whether or not anyone has connected. A team that turns up late loses that time.
- **Credits are not refundable to keys.** Returning credits means returning them to the balance, never
  trading items back to the user.

## Outstanding Clarifications

None blocking. All questions raised during specification have been answered and folded into the
requirements above; see **Clarifications**.

The constitution's standing follow-up TODO — *"define the concrete entitlement unit for a per-scrim
server (single credit vs. bundle)"* — **is now settled**: the unit is a **credit worth one hour of
runtime**, bought at 2 keys per 5 credits. The constitution should be amended to record this and drop
the TODO.

One item is recorded as an assumption rather than a decision, and is worth confirming before
implementation:

- Extensions are priced at double rate (a credit buys 60 minutes up front, 30 on an extension).
