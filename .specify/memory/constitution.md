<!--
Sync Impact Report
==================
Version change: 3.1.0 → 4.0.0
Rationale: MAJOR. Principle VIII's authority model is **redefined**, not expanded. v3.1.0 said the
           requester "individually owns" the server they are granted and that an auto-started server
           is "owned by the team that scheduled it". Both are now wrong: *joining* extends to both
           teams in the scrim, and *controlling* narrows to the RGL-designated leaders of the
           organising team. A deployment built to v3.1.0 would grant control to a captain who, under
           v4.0.0, may hold none — code correct against the old rule is incorrect against the new
           one, which is what backward-incompatible means here.

           The amendment also introduces a governance separation that did not previously exist:
           **paying for a server and controlling it are distinct.** A claiming team can buy the
           server for a match another team organised, in which case the organiser's leaders hold
           control and the payer holds access only.

           Judgement call worth recording: an argument exists for 3.2.0 on the grounds that the
           versioning policy's MINOR clause covers "materially changed guidance". Rejected — the
           change reverses who holds authority over paid compute, which is the substance of
           Principle VIII rather than its detail. Where a change alters who may act on someone
           else's paid resource, MAJOR is the honest reading.

Changes in this amendment:
  - IV.   Secure by Default → the RCON bullet now states that only the organising team's leaders may
          reach it, that the administrative password MUST NEVER be stored beside a server's joinable
          details or sent to any client, and that a join password is not an administrative one.
  - VIII. Free to Schedule, Approved to Provision → **redefined**. The old single "Binding" bullet
          becomes four:
            * Binding — unchanged mechanics (scrim-bound, window starts at the scheduled time,
              never outlives its credits), with the ownership claim removed.
            * Who may join — **both teams** in the scrim, with everything needed to connect. Outside
              those two teams a server MUST be indistinguishable from a nonexistent one.
            * Who may control it — **RGL-designated leaders of the proposing/posting team only**,
              re-checked server-side, read from RGL's roster data rather than an in-app role, with a
              documented fallback to the paying account when no leader is known (a server nobody can
              control is a worse failure than one its payer controls).
            * Paying vs controlling — explicitly separated, with extensions charged to whoever
              authorises them.
  - Scope & Non-Goals → "individual (captain) ownership of granted servers" replaced by the
          join/control split. The role-hierarchy non-goal is sharpened rather than loosened: RGL's own
          leader designation is in scope precisely because it is RGL's data and not ours to invent,
          while the platform still MUST NOT define roles of its own.

Prior amendments (retained for history): 1.1.0 → 2.0.0 redefined a free hobby PoC as a paid service;
2.0.0 → 2.1.0 moved payment out-of-band (request → operator approval, no PCI scope); 3.0.0 redefined
the product as scrims-first with servers as a paid attach; 3.1.0 settled the entitlement unit as a
credit worth one hour of runtime and named Steam trade offers as the first payment method.

Templates and docs requiring updates:
  - ✅ .specify/templates/plan-template.md — Constitution Check is generic ("[Gates determined based
        on constitution file]"); no edit needed.
  - ✅ .specify/templates/spec-template.md / tasks-template.md — no constitution references.
  - ✅ specs/005-servers-page/spec.md — FR-001, FR-008 and FR-027 updated to the join/control split;
        the implementation already behaves this way and was the source of this amendment.
  - ✅ README.md — "the owner of a granted server is the individual captain" corrected.
  - ⚠ docs/product-brief.md — §P1 and the user stories still frame a granted server as individually
        owned by its requesting captain.
  - ⚠ docs/constitution-seed.md — updated for v3.1.0's credit model but still describes individual
        captain ownership.

Follow-up TODOs:
  - Season-long rented servers remain in scope but have no defined unit of purchase. Credits cover
    per-scrim runtime only. Define the season-term unit before specifying that product.
  - A season-term server has no scrim and therefore no "organising team". Control currently falls back
    to the team the server is bound to; confirm that is the intended rule when season rental is
    specified.
  - RATIFICATION_DATE unchanged (2026-07-09, original adoption).
-->

# TF2 Server Hosting Constitution

## Core Principles

### I. Scrims First, Servers as the Upsell
The loop that defines this product is: **sign in with Steam → link an RGL identity → find or
arrange a scrim → optionally pay to have a server ready when it starts.** Scheduling MUST be
**free and complete on its own** — a team that never pays a cent MUST still be able to post
listings, claim them, propose matches, see rosters, and track attendance. Paid work MUST attach to
a scrim that already exists rather than standing in front of it. Scheduling MUST NEVER be blocked,
delayed, or made to fail by anything to do with payment, credit balance, or the availability of a
payment provider. Every increment MUST advance or harden this loop, and when two designs both work,
the smallest one that works wins.
**Rationale:** Scheduling is the habit teams come back to every week; servers are what that habit
can be sold. Gating the scheduling surface behind payment would leave nobody to sell to, and a
half-built scheduling tool makes the paid attach worthless.

### II. Servers Are Cattle, Not Pets
Every server MUST be fully described by code and config and MUST be disposable. Two lifecycles are
in scope and both MUST reclaim **workload, Service, PVC, and MetalLB IP** without manual help:
- **Per-scrim**: created early enough to be joinable at its scrim's **scheduled start time**, and
  destroyed once its **runtime window** has elapsed — that window being the time its credits entitle
  it to, plus any extensions, plus a single bounded unpaid grace period. Matches commonly overrun,
  so that grace MUST exist; it MUST be granted once per server rather than once per window, or
  repeated extension becomes a way to accumulate free time. At the end of the grace an un-extended
  server MUST stop, and its team MUST be able to see that it stopped because time ran out rather
  than because something broke.
- **Season-term**: suspend → grace period (config and maps retained so the owner can renew) →
  delete and reclaim.
No server may depend on manual, one-off, in-place mutation to reach or stay in its desired state.
**Rationale:** Per-scrim servers turn creation and destruction into a daily, high-volume event. A
resource leak that was survivable once a season becomes a continuous drain on shared capacity. And
a server that outlives what was paid for it is a leak of a different kind.

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
  submitted ids. A Steam sign-in assertion MUST be verified as having been issued **to this
  deployment**, not merely as validly signed.
- **RCON & secrets:** no server is reachable without an RCON password; RCON MUST NEVER be exposed
  to players — only the control plane speaks it, and only on behalf of the organising team's leaders
  (Principle VIII). The administrative password MUST NEVER be stored alongside a server's joinable
  details nor delivered to any client; a join password is not an administrative one. Secrets (RCON
  passwords, tokens, API keys) MUST come from OpenBao and MUST NEVER be hardcoded or logged.
- **Payments:** the platform MUST NOT process or store card or bank details, and MUST NOT move money
  itself. Payment completes on the payment provider's own surface, out-of-band from the app, which
  only ever **observes the result**. **Steam trade offers are the first supported method**; more are
  planned, so the entitlement and granting model MUST remain method-agnostic — adding a method MUST
  NOT require changing how credits are granted, reserved, or spent. Any credential used to observe
  payments MUST come from OpenBao, MUST NEVER be committed or logged, and MUST NEVER reach a client.
  A payment the provider would not complete in time to be useful MUST be refused up front rather
  than accepted and left hanging.
**Rationale:** Keeping money entirely outside the app removes PCI scope and payment-fraud surface;
a single leaked secret or exposed admin channel is still an immediate takeover risk, so identity,
secrets, and RCON stay locked down by default. Taking payment for something that cannot be delivered
in time is its own kind of harm.

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
fail visibly to its team rather than silently degrade the cluster — and MUST NOT consume the credits
reserved for it. Public exposure is in scope: DDoS resilience and abuse controls are first-class
requirements (competitive TF2 servers are common attack targets), and a publicly listed server
requires a Steam Game Server Login Token (GSLT).
**Rationale:** Shared bare-metal capacity means one unbounded or attacked tenant can take down
paying customers on the same nodes, and scrim traffic is bursty by nature — 8pm Sunday is not the
moment to discover the IP pool is exhausted. A team charged for a server they never got is worse
than one told plainly that it could not be placed.

### VIII. Free to Schedule, Approved to Provision
Access has two tiers, and only the second one costs money:
- **Schedule (free):** users authenticate via **Steam OpenID** and link an **RGL** identity; that
  verified pair is the account. Every account starts **free, holding no credits**, and any such user
  gets the full scrim surface — listings, proposals, claims, rosters, attendance, opponent discovery
  — at no charge. Team authority comes from RGL membership, re-checked server-side.
- **Provision (paid):** no server is created, started, or kept running without **credits** the
  operator has granted. **A credit is one hour of server runtime** — the single entitlement unit for
  per-scrim play. Credits are reserved when a server is attached to a scheduled scrim and consumed
  as that server runs; **extending a running server costs one credit per 30 minutes**. Credits MUST
  NOT expire, MUST belong to the account that paid for them, and MUST be enforced server-side. The
  exchange rate between payment and credits is configuration, not constitution, and may move with
  the market. Credits MUST NOT be spent for time a server did not get: a server that never started,
  or that failed to be placed, MUST return them.
- **Granting:** the operator handles payment out-of-band, and **their acceptance of that payment is
  the recorded granting act.** The platform observes the completed payment and credits the account.
  It MUST NOT grant credits on a client's assertion of having paid, and MUST NOT grant them for a
  payment that has not completed. Every movement of a credit balance MUST be recorded with its cause
  so a disputed balance can be explained without the operator's help.
- **Binding:** an auto-started server MUST be bound to a specific scheduled scrim. Its runtime window
  MUST begin at that scrim's **scheduled start time**, with the server ready to join by then; time
  spent getting it ready MUST NOT be charged. It MUST NOT outlive its credits (per-scrim → stopped and
  reclaimed at the end of its window; season → suspend → grace → delete).
- **Who may join (both sides):** a per-scrim server MUST be visible and joinable to **every member of
  both teams in that scrim**, and MUST surface everything needed to connect — address, and join
  password when set. A match has two sides and both have to get onto the server; a team that could not
  see the address could not play the match it is party to. Nobody outside those two teams may see it,
  and an inaccessible server MUST be indistinguishable from a nonexistent one.
- **Who may control it (organising leaders only):** changing a server's configuration, issuing
  administrative commands, and buying it more time MUST be restricted to **RGL-designated leaders of
  the team that proposed the scrim or posted the listing**, re-checked server-side. Leadership MUST be
  read from RGL's own roster data, never from an in-app role. Where no leader is known — a team whose
  roster has never been fetched — control MUST fall back to the account that paid, because a server
  nobody can control is a worse failure than one its payer controls.
- **Paying and controlling are separate:** the account that paid is not necessarily the account that
  controls. If a claiming team buys the server for a match another team organised, the organising
  team's leaders hold control and the payer holds access. Credits still belong to the account that
  bought them (see *Provision*), and an extension is charged to whoever authorises it.
- **Honesty about what is on offer:** an action that spends credits MUST NOT be offered to an account
  whose balance cannot cover it. The route to obtaining credits MUST be shown in its place, so the
  absence of the action is never unexplained.
**Rationale:** Free scheduling is what makes the platform worth opening; a server-side entitlement —
not a client assertion — decides who gets compute, while payment stays entirely outside the app.
Pricing runtime by the hour rather than by the match is what lets one payment cover a season of
scrims, which matters because every payment costs the operator a manual acceptance. Splitting *join*
from *control* is what makes a shared server usable: eighteen players need the address, but a match
has one organiser, and configuration drifting between two teams mid-scrim serves nobody. Sourcing
leadership from RGL rather than the app keeps authority in one place and true as rosters change.

## Scope & Non-Goals

The product is a **free scrim scheduling platform for competitive Team Fortress 2 teams, with paid
dedicated servers attached to the scrims they schedule.** A player signs in with Steam, links their
RGL account, and immediately gets the scrim surface: browse open listings across the league, post
their own, propose a match to any team in their format's current season, claim someone else's,
inspect the opposing roster, and track who on their own team is showing up. When a team wants
somewhere to actually play, they pay the operator out-of-band for **credits** — hours of server
runtime — and spend them on a scrim they have scheduled: a **per-scrim server** started for that
match and reclaimed after it, or a **season-long rented server** (a permanent home they own and
configure for the term). Granted servers are publicly joinable and RCON-manageable through the web
console.

**In scope (defining):** Steam OpenID sign-in; RGL account/team linking; the free scrim surface
(dashboard, open listings, directed proposals, claims, rosters, attendance, division-based opponent
discovery); **credits as the unit of paid server runtime, and the payment methods that grant them —
Steam trade offers first, others to follow**; a recorded credit ledger; per-scrim server auto-start
bound to a scheduled match, with extension and a bounded overrun grace; season-long server rental
with its term lifecycle; both teams in a scrim able to join its server while only the organising
team's RGL leaders configure it; public reachability of
granted servers.

**Out of scope (this phase), and MUST NOT be designed in (though not actively precluded):** in-app
or automated payment processing — payment completes on the provider's own surface and the app only
observes the result, never moving money itself; recurring subscriptions and pay-as-you-go/hourly
billing beyond the credit model above; refunding credits back into whatever was paid for them;
in-app role hierarchies — RGL's own leader designation is in scope precisely because it is RGL's
data and not ours to invent, but the platform MUST NOT define roles of its own beyond that plus the
creator of a listing; multi-region; games
other than TF2; SLAs or uptime guarantees; notifications and reminders.

Target environment: deploys to the bare-metal `mke` Kubernetes cluster (Flannel CNI); public game
traffic uses a MetalLB UDP address pool (one `LoadBalancer` Service per server); the control plane is
Python / Flask (served by Gunicorn), driving the cluster via the official Kubernetes Python client;
the custom game-server image lives in `harbor.irulast.com`; secrets come from OpenBao; RGL data comes
from the public `api.rgl.gg` endpoints, cached locally and degraded gracefully when unreachable.

## Development Workflow

Work follows the Spec Kit spec-driven flow, seeded by the documents in `docs/`:
`/constitution` → `/specify` → `/plan` → `/tasks` → `/implement`. Specs describe user-observable
behavior; technology and architecture choices live in the plan, not the spec. Build order validates
the riskiest unproven pieces first. The free scheduling loop is proven end-to-end in features
002–004 (Steam sign-in, RGL linking, scrim scheduling, rosters, attendance, opponent discovery).
Feature 005 specifies the paid surface against the credit model above, deliberately making the
**payment and entitlement loop real while leaving server provisioning simulated** — so the money
path can be proven before the cluster work begins. The unproven risk that still gates delivery is
therefore **provisioning bound to a scrim**: MetalLB UDP exposure, RCON control, and
auto-start/teardown timed to a scheduled match and to a runtime window.

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

**Version**: 4.0.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-29
