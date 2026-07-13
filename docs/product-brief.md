# Product Brief — TF2 Server Hosting

> **Purpose of this file.** This is the *what & why* of the product, written to be
> pasted into Spec Kit's **`/specify`** step. It deliberately avoids technology
> and implementation detail — those belong in [`tech-context.md`](tech-context.md)
> and the later `/plan` step. Keep this focused on user-observable behavior.

## Ready-to-paste `/specify` prompt

> Build a paid, self-service web application for **competitive Team Fortress 2 teams
> to rent a dedicated game server for a season**. A visitor signs in with **Steam**.
> To get a server, a signed-in captain **submits a server request** (their desired
> settings and how long they need it for the season). The **operator handles payment
> out-of-band and approves** the request — the app itself never processes payments.
> Only after approval is a server provisioned; within about a minute it becomes
> publicly joinable and the captain is shown a public address (IP and port) to share
> with their players. The owner can start, stop, restart, and delete their server, see
> live status (online/offline, current map, connected players out of max slots), and
> edit basic settings — server name, starting map, max slots, and a join password. Each
> server has a web-based **admin console** for remote admin commands (change the map,
> kick or ban a player, run server commands) backed by RCON. When the season term ends,
> the server is **suspended**, its config is retained for a grace period so the owner can
> renew, then it is deleted and its resources reclaimed. The buyer is an individual owner
> (the captain); no multi-member team accounts yet.

## Problem

Competitive TF2 teams need a reliable dedicated server for their weekly scrims across
a season. Standing one up by hand is fiddly (SteamCMD, `server.cfg`, UDP ports, RCON,
patching). Free tools like serveme.tf give you an ad-hoc server per session but nothing
that's *yours* for the season. Commercial hosts are pricier and clunkier than a team
needs. This turns "our team needs a scrim server for the season" into: sign in with
Steam, request a server, and once it's approved it's yours until the season ends.

## Who it's for

- **Team captain / owner** — a Steam-authenticated user who requests a server, and once
  approved owns it, configures it, shares the address with their players, and
  administers it live. This is the paying customer (payment arranged with the operator).
- **Player** — anyone the owner shares the address with; they just connect in the TF2
  client. Players do **not** use this app.
- **Operator** — Irulast, running the platform on `mke`; reviews and **approves** server
  requests, handles payment **out-of-band**, and cares about not leaving orphaned servers
  eating cluster resources.

## User stories (prioritized)

**P1 — the core paid loop (must exist to mean anything)**
- As a visitor, I can sign in with Steam.
- As a signed-in captain, I can submit a **server request** for the season.
- As an operator, I can review a request and **approve** it (after arranging payment
  out-of-band) — or decline it.
- As a captain, only after my request is approved is my server provisioned.
- As a captain, once created, I'm shown the public address (IP:port) to share, and I can
  connect from the TF2 client and it works.
- As an operator, when a season term ends the server suspends, keeps its config for a
  grace period, then is deleted and its cluster resources are reclaimed.

**P2 — control & administration**
- As a captain, I can start, stop, and restart my server.
- As a captain, I can see live status: online/offline, current map, player count/slots.
- As a captain, I can open a web console and run admin commands (`changelevel`, `kick`,
  `status`) and see the output.
- As a captain, I can see and rotate my server's RCON password.

**P3 — configuration & account**
- As a captain, I can set the server name (hostname), starting map, max slots, and an
  optional join password before/at creation.
- As a captain, I can edit those settings and apply them (restarting if needed).
- As a captain, I can see my server's term — end date and remaining time — and request a
  renewal before it lapses.

## Acceptance signals

- A signed-in captain whose request is **approved** gets a joinable TF2 server at the
  shown address in under ~2 minutes; a captain whose request is **not** approved never
  gets a server.
- The web console can run `status` and `changelevel` against a running server and show
  the result.
- At term end the server suspends, its config survives the grace period, and after the
  grace period deletion frees its cluster resources and its public address.
- No server is publicly reachable without an RCON password set, and RCON is never exposed
  to players.

## Explicitly out of scope (first version)

In-app or automated payment processing (the operator handles payment out-of-band) ·
recurring subscriptions and pay-as-you-go/hourly billing · multi-member team accounts and
roles · a free tier · SLAs / uptime guarantees · multi-region · non-TF2 games. These may
come later; do not design the first version around them, but don't actively preclude them.
(Note: DDoS resilience and Steam GSLT for public listing are **in scope** as servers are
publicly reachable — see the constitution.)

## Open questions to resolve during `/clarify`

- What's in a server request (term length, desired specs) and what does the operator see
  to approve it?
- Season term length, and how renewal works (extend the same server vs. a new term)?
- What exactly is the grace period after term end before deletion?
- Quotas: how many servers can one captain hold / how many run concurrently on the cluster?
- Are granted servers listed on the public Steam master server (needs GSLT) or address-only?
- How is the requester notified of approval/decline?
