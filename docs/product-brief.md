# Product Brief — TF2 Server Hosting

> **Purpose of this file.** This is the *what & why* of the product, written to be
> pasted into Spec Kit's **`/specify`** step. It deliberately avoids technology
> and implementation detail — those belong in [`tech-context.md`](tech-context.md)
> and the later `/plan` step. Keep this focused on user-observable behavior.

## Ready-to-paste `/specify` prompt

> Build a **free scrim scheduling web application for competitive Team Fortress 2 teams,
> with paid dedicated servers attached to the scrims they schedule**. A visitor signs in
> with **Steam** and links their **RGL** account; that verified pair is the account, and
> it immediately unlocks the whole scheduling surface at no charge — a dashboard of the
> team's upcoming scrims, posting and browsing **open listings**, sending a **directed
> proposal** to a specific team in their format's current season, **claiming** someone
> else's listing, inspecting the **opposing roster**, tracking **attendance** on their own
> team, and finding opponents by **division**. None of that is ever gated behind payment.
> When a team wants somewhere to actually play, they arrange payment with the **operator
> out-of-band** and the operator **records an approval** — the app itself never processes
> payments. An approval grants one of two things: a **per-scrim server**, auto-started for
> one specific scheduled scrim, owned by the team that scheduled it, and destroyed once
> that match is over; or a **season-long rented server** the captain owns and configures
> for the whole term. Either way the captain is shown a public address (IP and port) to
> share with their players; the owner can start, stop, restart, and delete the server, see
> live status (online/offline, current map, connected players out of max slots), and edit
> basic settings — server name, starting map, max slots, and a join password. Each server
> has a web-based **admin console** for remote admin commands (change the map, kick or ban
> a player, run server commands) backed by RCON. A per-scrim server never outlives its
> match; when a season term ends the rented server is **suspended**, its config is retained
> for a grace period so the owner can renew, then it is deleted and its resources
> reclaimed.

## Problem

Competitive TF2 teams do two chores every week. First they have to *find* the scrim —
trawling Discord and league channels for a team in their division that's free the same
night, agreeing on it, and then keeping track of who on their own roster is actually
showing up. Then they need somewhere to play it. Standing a server up by hand is fiddly
(SteamCMD, `server.cfg`, UDP ports, RCON, patching); free tools like serveme.tf give you
an ad-hoc server per session but nothing that's *yours*, and commercial hosts are pricier
and clunkier than a team needs. This makes the scheduling half **free and complete on its
own** — sign in with Steam, link RGL, arrange the match — and sells the half teams have to
pay someone for anyway: a server that's ready when the scrim starts, or a permanent home
for the season.

## Who it's for

- **Team member** — any Steam-authenticated user with a linked RGL account. This is the
  free tier and it is the bulk of the product: they browse and post listings, propose and
  claim scrims, look at opposing rosters, and mark attendance, without ever paying. Team
  authority comes from **RGL membership**, re-checked server-side.
- **Team captain / server owner** — the member who wants a server for a scrim their team
  already scheduled, or for the whole season. They arrange payment with the operator and,
  once approved, own the granted server, configure it, share the address with their
  players, and administer it live. This is the paying customer.
- **Player** — anyone the owner shares the address with; they just connect in the TF2
  client. Players do **not** use this app.
- **Operator** — Irulast, running the platform on `mke`; handles payment **out-of-band**,
  reviews and **approves** entitlements, and cares about not leaving orphaned servers
  eating cluster resources.

## User stories (prioritized)

**P1 — the free scrim loop (must exist to mean anything)**
- As a visitor, I can sign in with Steam.
- As a signed-in user, I can link my **RGL** account and see the team(s) I belong to.
- As a team member, I can see a dashboard of my team's upcoming and past scrims.
- As a team member, I can post an **open listing** for a slot we're free to play, and
  browse and **claim** other teams' open listings.
- As a team member, I can send a **directed proposal** to a specific team in my format's
  current season, and accept or decline proposals sent to us.
- As a team member, I can browse teams by **division** to find opponents worth playing.
- As a team member, I can inspect the **opposing roster** for a scheduled scrim.
- As a team member, I can mark and track **attendance** for my own team's scrims.
- As a team member, I can do all of the above without ever paying anything.

**P2 — paid servers attached to a scrim (the next priority)**
- As a captain, I can ask for a server for a scrim my team has already scheduled, or for
  the season.
- As an operator, I can review that ask and **record an approval** granting an
  entitlement (after arranging payment out-of-band) — or decline it.
- As a captain, only with an approved entitlement is a server ever provisioned.
- As a captain with a **per-scrim** entitlement, the server for that scrim is started for
  me shortly before its scheduled start, is bound to that scrim and owned by my team, and
  is destroyed once the match is over.
- As a captain with a **season term**, I get a rented server I own and configure for the
  whole term.
- As a captain, I'm shown the public address (IP:port) to share, and I can connect from
  the TF2 client and it works.
- As a team, if a scheduled scrim's server can't be placed, I'm told so visibly rather
  than finding out at match time.
- As an operator, when a season term ends the server suspends, keeps its config for a
  grace period, then is deleted and its cluster resources are reclaimed.

**P3 — control & administration**
- As a captain, I can start, stop, and restart my server.
- As a captain, I can see live status: online/offline, current map, player count/slots.
- As a captain, I can open a web console and run admin commands (`changelevel`, `kick`,
  `status`) and see the output.
- As a captain, I can see and rotate my server's RCON password.

**P4 — configuration & account**
- As a captain, I can set the server name (hostname), starting map, max slots, and an
  optional join password before/at creation.
- As a captain, I can edit those settings and apply them (restarting if needed).
- As a captain, I can see my season server's term — end date and remaining time — and
  request a renewal before it lapses.

## Acceptance signals

- A Steam-authenticated, RGL-linked user who never pays can post a listing, have it
  claimed, see the opposing roster, and track attendance for the resulting scrim — the
  whole scheduling loop, with nothing gated behind payment.
- A scheduled scrim whose team holds an **approved** entitlement has a joinable TF2 server
  at the shown address before its scheduled start; a scrim with no approved entitlement
  never gets a server.
- A per-scrim server is bound to exactly one scheduled scrim and is torn down after that
  match, freeing its cluster resources and public address.
- The web console can run `status` and `changelevel` against a running server and show
  the result.
- At term end the season server suspends, its config survives the grace period, and after
  the grace period deletion frees its cluster resources and its public address.
- No server is publicly reachable without an RCON password set, and RCON is never exposed
  to players.

## Explicitly out of scope (first version)

In-app or automated payment processing (the operator handles payment out-of-band) ·
recurring subscriptions and pay-as-you-go/hourly billing · in-app role hierarchies beyond
RGL membership (plus the creator of a listing) · notifications and reminders · SLAs /
uptime guarantees · multi-region · non-TF2 games. These may come later; do not design the
first version around them, but don't actively preclude them. (Note: DDoS resilience and
Steam GSLT for public listing are **in scope** as servers are publicly reachable — see the
constitution.)

## Open questions to resolve during `/clarify`

- What is the entitlement unit for a per-scrim server — a single credit per match, a
  bundle, or something else? **Undecided**; the constitution flags this as a follow-up to
  settle before the first provisioning feature is specified.
- What's in an ask for a server (which scrim or which term, desired settings) and what
  does the operator see to approve it?
- How long before a scrim's scheduled start is its server created, and how long after the
  match ends is it destroyed?
- Season term length, and how renewal works (extend the same server vs. a new term)?
- What exactly is the grace period after term end before deletion?
- Quotas: how many servers can one team hold, and what's the cap on servers the platform
  will auto-start concurrently?
- Are granted servers listed on the public Steam master server (needs GSLT) or address-only?
