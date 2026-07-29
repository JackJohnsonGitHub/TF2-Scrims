<!--
Sync Impact Report
==================
Version change: 3.0.0 → 3.1.0
Rationale: MINOR. No principle is added or removed and no core rule is reversed; this amendment
           *completes* a decision v3.0.0 explicitly deferred to a follow-up TODO — the concrete
           entitlement unit — and names the first payment method. Principle VIII's non-negotiable
           rule is unchanged (a server-side-enforced, operator-granted entitlement gates compute);
           what changes is that the entitlement now has a defined unit (a credit worth one hour of
           runtime) and the granting act has a defined mechanism (the operator accepting payment).
           Principles II and IV gain materially expanded guidance rather than new obligations.

           Judgement call worth recording: an argument exists for MAJOR, on the grounds that
           "operator approves an entitlement" previously implied a deliberate in-app approval step
           and now resolves to "the operator accepted the payment". That is a mechanism change, not
           a governance reversal — the operator's deliberate, recorded act still gates compute and
           is still never inferred from client input — so MINOR is the honest reading. Revisit as
           4.0.0 if the project decides the approval *surface* was itself constitutional.

Changes in this amendment:
  - II.   Servers Are Cattle → the per-scrim lifecycle is now defined by a **runtime window**: created
          early enough to be joinable at the scrim's scheduled start, destroyed once the window,
          any extensions, and a single bounded unpaid grace period have elapsed.
  - IV.   Secure by Default → the payments bullet names **Steam trade offers as the first supported
          method**, requires the model stay method-agnostic as more are added, classes any
          payment-observing credential as an OpenBao secret, and forbids accepting a payment the
          provider would not complete in time to be useful.
  - VIII. Free to Schedule, Approved to Provision → the entitlement unit is settled: **a credit is
          one hour of server runtime**. Credits are reserved against a scheduled scrim, consumed as
          the server runs, cost one credit per 30 minutes to extend, never expire, and belong to the
          paying account. The granting act is the operator's acceptance of payment, observed by the
          platform rather than asserted by a client. A runtime window begins at the scrim's scheduled
          start; provisioning time is not charged.
  - Scope & Non-Goals → credits and trade-based payment added to the in-scope list; the
          payment-processing non-goal clarified (the app observes a completed payment, it never
          moves money).
  - Development Workflow → records that feature 005 is specified against these terms.

Resolved from v3.0.0:
  - ✅ "Define the concrete entitlement unit for a per-scrim server (single credit vs. bundle) before
        the first provisioning feature is specified." — **DONE**: one credit = one hour of runtime;
        2 Mann Co. Supply Crate Keys grant 5 credits; extension costs 1 credit per 30 minutes. The
        rate itself is configuration, not constitutional, so it may move with the market without an
        amendment.

Prior amendments (retained for history): 1.1.0 → 2.0.0 redefined a free hobby PoC as a paid
service; 2.0.0 → 2.1.0 moved payment out-of-band (request → operator approval, no PCI scope);
3.0.0 redefined the product as scrims-first with servers as a paid attach.

Templates and docs requiring updates:
  - ✅ .specify/templates/plan-template.md — Constitution Check is generic ("[Gates determined based
        on constitution file]"); no edit needed.
  - ✅ .specify/templates/spec-template.md / tasks-template.md — no constitution references.
  - ✅ specs/005-servers-page/spec.md — already written against these terms; it is the source of
        this amendment.
  - ⚠ README.md — §"Scope of the first version" and the Monetization row still describe an
        entitlement as "a per-scrim server" granted by operator approval, with no mention of credits
        or trade payment.
  - ⚠ docs/product-brief.md — §P1 and the user stories still frame the entitlement as per-scrim vs
        season-term; its open-questions list (line ~138) still asks for the entitlement unit that
        this amendment settles, and should be struck.
  - ⚠ docs/constitution-seed.md — predates v3.0.0 as well as this amendment.
  - ⚠ specs/004-scrims-dashboard/plan.md — its recorded deviation from the old Principle I remains
        dissolved (see v3.0.0); no new action.

Follow-up TODOs:
  - Season-long rented servers remain in scope but have no defined unit of purchase. Credits cover
    per-scrim runtime only. Define the season-term unit before specifying that product.
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
  to players — only the control plane speaks it. Secrets (RCON passwords, tokens, API keys) MUST
  come from OpenBao and MUST NEVER be hardcoded or logged.
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
- **Binding:** an auto-started server MUST be bound to a specific scheduled scrim and owned by the
  team that scheduled it. Its runtime window MUST begin at that scrim's **scheduled start time**,
  with the server ready to join by then; time spent getting it ready MUST NOT be charged. It MUST
  NOT outlive its credits (per-scrim → stopped and reclaimed at the end of its window; season →
  suspend → grace → delete).
- **Honesty about what is on offer:** an action that spends credits MUST NOT be offered to an account
  whose balance cannot cover it. The route to obtaining credits MUST be shown in its place, so the
  absence of the action is never unexplained.
**Rationale:** Free scheduling is what makes the platform worth opening; a server-side entitlement —
not a client assertion — decides who gets compute, while payment stays entirely outside the app.
Pricing runtime by the hour rather than by the match is what lets one payment cover a season of
scrims, which matters because every payment costs the operator a manual acceptance.

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
with its term lifecycle; individual (captain) ownership of granted servers; public reachability of
granted servers.

**Out of scope (this phase), and MUST NOT be designed in (though not actively precluded):** in-app
or automated payment processing — payment completes on the provider's own surface and the app only
observes the result, never moving money itself; recurring subscriptions and pay-as-you-go/hourly
billing beyond the credit model above; refunding credits back into whatever was paid for them;
in-app role hierarchies beyond RGL membership plus the creator of a listing; multi-region; games
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

**Version**: 3.1.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-29
