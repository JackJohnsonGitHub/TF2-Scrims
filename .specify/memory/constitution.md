<!--
Sync Impact Report
==================
Version change: 2.1.0 → 3.0.0
Rationale: MAJOR. The product is redefined. Scrim scheduling — not server rental — is the core
           loop, and it is **free** for any Steam-authenticated, RGL-linked user. Paid servers
           become an upsell that attaches to a scrim a team already scheduled: a per-scrim server
           auto-started for that match (the entry point), or a season-long rented server (a
           permanent home). Two principles are redefined and the Scope & Non-Goals section is
           rewritten, including the removal of "a free tier" from the non-goals.

Changes in this amendment:
  - I.    "Ship the Smallest Paid Loop First" → "Scrims First, Servers as the Upsell". The loop to
          prove is sign in → link RGL → schedule a scrim → optionally pay for a server. Scrim
          scheduling MUST remain free and complete on its own.
  - II.   Servers Are Cattle → now governs TWO lifecycles: per-scrim (create before, destroy after)
          and season-term (suspend → grace → delete). Churn is higher, so reclamation is stricter.
  - VII.  Right-Size the Blast Radius → adds a cap on concurrently auto-started servers; a rush of
          scheduled scrims MUST NOT be able to exhaust node capacity or the MetalLB IP pool.
  - VIII. "Steam-Authenticated, Approved Access" → "Free to Schedule, Approved to Provision".
          Identity gates the scrim surface (free); recorded operator approval gates compute; an
          auto-started server MUST be bound to a specific scheduled scrim.
  - Scope & Non-Goals → rewritten around the free scrim platform + paid server attach; "a free
          tier" REMOVED from non-goals (the scrim surface is the free tier); in-app role
          hierarchies beyond RGL membership added to non-goals.
  - Development Workflow → build order updated: the scrim loop is proven (003/004 shipped); the
          unproven risk is now provisioning bound to a scrim (MetalLB UDP, RCON, auto-start).

Prior amendments (retained for history): 1.1.0 → 2.0.0 redefined a free hobby PoC as a paid
service; 2.0.0 → 2.1.0 moved payment out-of-band (request → operator approval, no PCI scope).

Templates requiring updates:
  - ✅ .specify/templates/plan-template.md / spec-template.md / tasks-template.md — constitution
        references are generic ("[Gates determined based on constitution file]"); no edits needed.
  - ✅ README.md — product framing, status, and scope rewritten to the scrims-first model.
  - ⚠ docs/product-brief.md — still describes the core paid loop as renting a season server (§P1).
  - ⚠ docs/tech-context.md — still frames the buyer as purchasing a server ("purchase → joinable").
  - ⚠ docs/constitution-seed.md — seed principle 1 and its non-goals predate this amendment.
  - ⚠ specs/004-scrims-dashboard/plan.md — its Constitution Check records a *justified deviation*
        from the old Principle I for building scrim UX ahead of the paid loop. That deviation is
        DISSOLVED by this amendment: 004 is now core-loop work, not a deviation. The historical
        note may stay, but future analyze/converge runs should stop treating it as an open item.

Follow-up TODOs:
  - Define the concrete entitlement unit for a per-scrim server (single credit vs. bundle) before
    the first provisioning feature is specified.
  - RATIFICATION_DATE unchanged (2026-07-09, original adoption).
-->

# TF2 Server Hosting Constitution

## Core Principles

### I. Scrims First, Servers as the Upsell
The loop that defines this product is: **sign in with Steam → link an RGL identity → find or
arrange a scrim → optionally pay to have a server ready when it starts.** Scheduling MUST be
**free and complete on its own** — a team that never pays a cent MUST still be able to post
listings, claim them, propose matches, see rosters, and track attendance. Paid work MUST attach to
a scrim that already exists rather than standing in front of it. Every increment MUST advance or
harden this loop, and when two designs both work, the smallest one that works wins.
**Rationale:** Scheduling is the habit teams come back to every week; servers are what that habit
can be sold. Gating the scheduling surface behind payment would leave nobody to sell to, and a
half-built scheduling tool makes the paid attach worthless.

### II. Servers Are Cattle, Not Pets
Every server MUST be fully described by code and config and MUST be disposable. Two lifecycles are
now in scope and both MUST reclaim **workload, Service, PVC, and MetalLB IP** without manual help:
- **Per-scrim**: created shortly before its scrim's scheduled start, destroyed once the match ends.
- **Season-term**: suspend → grace period (config and maps retained so the owner can renew) →
  delete and reclaim.
No server may depend on manual, one-off, in-place mutation to reach or stay in its desired state.
**Rationale:** Per-scrim servers turn creation and destruction into a daily, high-volume event. A
resource leak that was survivable once a season becomes a continuous drain on shared capacity.

### III. Kubernetes-Native Control
The control plane MUST manipulate the cluster through the Kubernetes API, using the official
Kubernetes client for the control plane's language (the Python client), not by shelling out to
`kubectl` or mutating running containers by hand. Authoritative state lives in Kubernetes objects
and the metadata store — never in an operator's head.
**Rationale:** Typed, API-driven control is reproducible, testable, and auditable; shelling out is
not.

### IV. Secure by Default
Identity, secrets, and payments are guarded by default:
- **Auth:** every account is a Steam-verified identity (Principle VIII). Free scrim features still
  require that identity; privileged actions require an authenticated session bound to it, and
  authority is always re-checked server-side against stored memberships — never inferred from
  submitted ids.
- **RCON & secrets:** no server is reachable without an RCON password; RCON MUST NEVER be exposed
  to players — only the control plane speaks it. Secrets (RCON passwords, tokens, API keys) MUST
  come from OpenBao and MUST NEVER be hardcoded or logged.
- **Payments:** the platform MUST NOT process or store any payment or card data. Payment is
  handled **out-of-band by the operator** for both paid products; compute is granted only by an
  **explicit, recorded operator approval**, verified server-side.
**Rationale:** Keeping money entirely outside the app removes PCI scope and payment-fraud surface;
a single leaked secret or exposed admin channel is still an immediate takeover risk, so identity,
secrets, and RCON stay locked down by default.

### V. Reproducible Images
The game-server image MUST be built from a pinned SteamCMD / SourceMod recipe and pushed to
`harbor.irulast.com`. Rebuilds MUST be deterministic. Running containers MUST NOT be mutated by
hand to change behavior — changes go through a rebuilt, re-pushed image.
**Rationale:** Deterministic images make "scrim starts → server is ready" predictable and let any
server be recreated identically.

### VI. Everything as Code
Cluster manifests, image builds, and config templates MUST live in this repository under version
control. Changes reach the cluster through the repo, not by hand on the cluster.
**Rationale:** The repo is the single source of truth; out-of-band changes cannot be reviewed,
reverted, or reproduced.

### VII. Right-Size the Blast Radius
Every server MUST have enforced CPU and memory limits and quotas so one tenant cannot starve the
node or the cluster. Because scrims cluster into evenings, the number of servers the platform will
auto-start concurrently MUST be bounded, and a scheduled scrim whose server cannot be placed MUST
fail visibly to its team rather than silently degrade the cluster. Public exposure is in scope:
DDoS resilience and abuse controls are first-class requirements (competitive TF2 servers are common
attack targets), and a publicly listed server requires a Steam Game Server Login Token (GSLT).
**Rationale:** Shared bare-metal capacity means one unbounded or attacked tenant can take down
paying customers on the same nodes, and scrim traffic is bursty by nature — 8pm Sunday is not the
moment to discover the IP pool is exhausted.

### VIII. Free to Schedule, Approved to Provision
Access has two tiers, and only the second one costs money:
- **Schedule (free):** users authenticate via **Steam OpenID** and link an **RGL** identity; that
  verified pair is the account. Any such user gets the full scrim surface — listings, proposals,
  claims, rosters, attendance, opponent discovery — at no charge. Team authority comes from RGL
  membership, re-checked server-side.
- **Provision (paid):** no server is created, started, or kept running without an **operator-
  approved entitlement** — either a **per-scrim server** for one scheduled match or a
  **season term** for a rented server. The operator approves after handling payment out-of-band;
  the approval and its scope are authoritative and enforced server-side, never inferred from
  client input.
- **Binding:** an auto-started server MUST be bound to a specific scheduled scrim and owned by the
  team that scheduled it, and it MUST NOT outlive its entitlement (per-scrim → destroyed after the
  match; season → suspend → grace → delete).
**Rationale:** Free scheduling is what makes the platform worth opening; a server-side approval —
not a client assertion — decides who gets compute, while payment stays entirely outside the app.

## Scope & Non-Goals

The product is a **free scrim scheduling platform for competitive Team Fortress 2 teams, with paid
dedicated servers attached to the scrims they schedule.** A player signs in with Steam, links their
RGL account, and immediately gets the scrim surface: browse open listings across the league, post
their own, propose a match to any team in their format's current season, claim someone else's,
inspect the opposing roster, and track who on their own team is showing up. When a team wants
somewhere to actually play, they pay the operator out-of-band and the operator approves an
entitlement: a **per-scrim server** (the entry point — spun up for that match, torn down after) or
a **season-long rented server** (a permanent home they own and configure for the term). Granted
servers are publicly joinable and RCON-manageable through the web console.

**In scope (defining):** Steam OpenID sign-in; RGL account/team linking; the free scrim surface
(dashboard, open listings, directed proposals, claims, rosters, attendance, division-based opponent
discovery); operator review and approval of paid entitlements; per-scrim server auto-start bound to
a scheduled match; season-long server rental with its term lifecycle; individual (captain)
ownership of granted servers; public reachability of granted servers.

**Out of scope (this phase), and MUST NOT be designed in (though not actively precluded):** in-app
or automated payment processing (payment is handled out-of-band by the operator); recurring
subscriptions and pay-as-you-go/hourly billing; in-app role hierarchies beyond RGL membership plus
the creator of a listing; multi-region; games other than TF2; SLAs or uptime guarantees;
notifications and reminders.

Target environment: deploys to the bare-metal `mke` Kubernetes cluster (Flannel CNI); public game
traffic uses a MetalLB UDP address pool (one `LoadBalancer` Service per server); the control plane is
Python / Flask (served by Gunicorn), driving the cluster via the official Kubernetes Python client;
the custom game-server image lives in `harbor.irulast.com`; secrets come from OpenBao; RGL data comes
from the public `api.rgl.gg` endpoints, cached locally and degraded gracefully when unreachable.

## Development Workflow

Work follows the Spec Kit spec-driven flow, seeded by the documents in `docs/`:
`/constitution` → `/specify` → `/plan` → `/tasks` → `/implement`. Specs describe user-observable
behavior; technology and architecture choices live in the plan, not the spec. Build order validates
the riskiest unproven pieces first. The free scheduling loop is now proven end-to-end in features
002–004 (Steam sign-in, RGL linking, scrim scheduling, rosters, attendance, opponent discovery);
the unproven risk that gates revenue is **provisioning bound to a scrim** — MetalLB UDP exposure,
RCON control, and auto-start/teardown timed to a scheduled match.

## Governance

This constitution supersedes ad-hoc practices for this project. Amendments MUST be made by editing
`.specify/memory/constitution.md`, MUST include a version bump per the policy below, and MUST update
the Sync Impact Report at the top of the file.

Versioning policy (semantic):
- **MAJOR** — backward-incompatible governance or principle removals/redefinitions.
- **MINOR** — a new principle or section, or materially expanded/changed guidance.
- **PATCH** — clarifications, wording, or non-semantic refinements.

Compliance: `/plan` runs a Constitution Check gate against these principles; any violation MUST be
justified in the plan's Complexity Tracking section or the design MUST be simplified. When a
principle and expedience conflict, the principle wins unless the constitution is formally amended.

**Version**: 3.0.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-27
