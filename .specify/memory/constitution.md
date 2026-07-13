<!--
Sync Impact Report
==================
Version change: 2.0.0 → 2.1.0
Rationale: MINOR. Payment is no longer processed in-app. Teams APPLY/REQUEST a server; the
           operator handles payment OUT-OF-BAND and approves the request. Access is still paid
           and gated, and the season-term lifecycle is unchanged — only the mechanism changes
           (no PCI processor, no in-app card handling, no automated webhooks). The app never
           touches money.

Changes in this amendment:
  - IV.   Secure by Default → payment-security bullet REPLACED: the app never processes or stores
          payment/card data; access is granted by explicit, recorded operator approval.
  - VIII. Steam-Authenticated, Paid Access → REFRAMED as request→operator-approval: no server is
          provisioned without an approved server request (operator approves after handling payment
          out-of-band). Entitlement = an approved request with a term.
  - Scope & Non-Goals → season-pass purchase via a processor replaced by "apply for a server,
          operator handles payment out-of-band and approves"; automated/online payment processing
          moved to out-of-scope.

Prior amendment (1.1.0 → 2.0.0, retained): redefined the product from a free hobby PoC into a paid
service for competitive TF2 teams (Steam sign-in, seasonal server, individual/captain ownership,
suspend→grace→delete lifecycle); added Principle VIII; rewrote Scope & Non-Goals.

Templates requiring updates:
  - ✅ .specify/templates/plan-template.md / spec-template.md / tasks-template.md — generic
        constitution references (no hardcoded principles); no edits needed.

Follow-up TODOs:
  - ✅ docs/product-brief.md, docs/tech-context.md, docs/constitution-seed.md, README.md — updated to
        the paid team model; being re-reconciled to the request/out-of-band-payment model with this
        amendment.
  - ⚠ Existing feature specs/001-basic-flask-app assumed "no auth, internal-only". That scaffold
        stands, but Steam auth (feature 002) and the server-request flow are now the active features;
        001's internal-only exposure assumption must be revisited before going public.
  - RATIFICATION_DATE unchanged (2026-07-09, original adoption).
-->

# TF2 Server Hosting Constitution

## Core Principles

### I. Ship the Smallest Paid Loop First
Prove the core paid loop — **sign in with Steam → request a server → operator approves (payment
handled out-of-band) → get a publicly joinable, RCON-manageable dedicated server for the season →
auto-expire and tear down at term end** — before building anything else. Every increment MUST
advance or harden that loop. When two designs both work, the smallest one that works wins over the
more general one. Work outside the loop (see Scope & Non-Goals) MUST NOT be built until the loop is
proven end-to-end, through a real approved request.
**Rationale:** Revenue and trust depend on the whole chain working — auth, request/approval,
provisioning, and teardown; generality bought before that chain is proven is speculative cost.

### II. Servers Are Cattle, Not Pets
Every rented server MUST be fully described by code and config and MUST be disposable. A server is
created on purchase and bound to its season-pass term; creating and destroying one is routine and
MUST leave no orphaned cluster resources — workload, Service, PVC, and MetalLB IP are all reclaimed
on delete. No server may depend on manual, one-off, in-place mutation to reach or stay in its
desired state.
**Rationale:** Disposability is what makes a paid, self-service fleet safe to operate; orphaned
resources silently drain the shared `mke` cluster and erode margins.

### III. Kubernetes-Native Control
The control plane MUST manipulate the cluster through the Kubernetes API, using the official
Kubernetes client for the control plane's language (the Python client), not by shelling out to
`kubectl` or mutating running containers by hand. Authoritative state lives in Kubernetes objects
and the metadata store — never in an operator's head.
**Rationale:** Typed, API-driven control is reproducible, testable, and auditable; shelling out is
not.

### IV. Secure by Default
Identity, secrets, and payments are guarded by default:
- **Auth:** every account is a Steam-verified identity (Principle VIII); privileged actions require
  an authenticated session bound to that identity.
- **RCON & secrets:** no server is reachable without an RCON password; RCON MUST NEVER be exposed to
  players — only the control plane speaks it. Secrets (RCON passwords, tokens, API keys) MUST come
  from OpenBao and MUST NEVER be hardcoded or logged.
- **Payments:** the platform MUST NOT process or store any payment or card data. Payment is
  handled **out-of-band by the operator**; access is granted only by an **explicit, recorded
  operator approval** of a server request, verified server-side (never inferred from client input).
**Rationale:** Keeping money entirely outside the app removes PCI scope and payment-fraud surface;
a single leaked secret or exposed admin channel is still an immediate takeover risk, so identity,
secrets, and RCON stay locked down by default.

### V. Reproducible Images
The game-server image MUST be built from a pinned SteamCMD / SourceMod recipe and pushed to
`harbor.irulast.com`. Rebuilds MUST be deterministic. Running containers MUST NOT be mutated by hand
to change behavior — changes go through a rebuilt, re-pushed image.
**Rationale:** Deterministic images make "purchase → joinable" predictable and let any server be
recreated identically.

### VI. Everything as Code
Cluster manifests, image builds, and config templates MUST live in this repository under version
control. Changes reach the cluster through the repo, not by hand on the cluster.
**Rationale:** The repo is the single source of truth; out-of-band changes cannot be reviewed,
reverted, or reproduced.

### VII. Right-Size the Blast Radius
Every server MUST have enforced CPU and memory limits and quotas so one tenant cannot starve the
node or the cluster. Because servers are now publicly sold and joined, public exposure is in scope:
DDoS resilience and abuse controls are first-class requirements (competitive TF2 servers are common
attack targets), and a publicly listed server requires a Steam Game Server Login Token (GSLT). These
MUST be addressed as the product goes public — not deferred indefinitely.
**Rationale:** Shared bare-metal capacity means one unbounded or attacked tenant can take down
paying customers on the same nodes; a paid service cannot hide behind "internal-only."

### VIII. Steam-Authenticated, Approved Access
Access is gated by identity and an approved request:
- Users authenticate via **Steam OpenID**; the verified Steam identity is the account. The
  **requester (team captain) is the individual owner** of the server they are granted, and shares
  connect information with their players.
- To get a server, a signed-in user submits a **server request**. No server is provisioned, started,
  or kept running without an **operator-approved request** carrying a season term. The operator
  approves after handling payment **out-of-band**; the approval and its term are authoritative and
  enforced server-side — never inferred from client input.
- At term end (or when an approval is withdrawn), the server follows **suspend → grace period
  (retain config/maps so the owner can renew without losing setup) → delete and reclaim**.
**Rationale:** This is what makes it a paid service rather than free hosting; an explicit,
server-side approval — not a client assertion — decides who gets compute, while payment stays
entirely outside the app.

## Scope & Non-Goals

The product is a **paid, self-service platform for competitive Team Fortress 2 teams** to rent a
dedicated (SRCDS) server for a season. A captain signs in with Steam and **submits a server
request**; the operator handles payment out-of-band and **approves** it. On approval the captain gets
a publicly joinable, RCON-manageable server they own and configure (hostname, starting map, max
slots, join password) and administer live via a web console. At term end the server suspends, retains
its config through a grace period, then is deleted and its resources reclaimed.

**In scope (defining):** Steam OpenID sign-in; in-app **server request** submission; operator review
and approval; individual (captain) ownership; per-season server lifecycle; public reachability of
granted servers.

**Out of scope (this phase), and MUST NOT be designed in (though not actively precluded):** in-app
or automated payment processing (payment is handled out-of-band by the operator); recurring
subscriptions and pay-as-you-go/hourly billing; team accounts with multiple managing members and
roles; multi-region; games other than TF2; a free tier.

Target environment: deploys to the bare-metal `mke` Kubernetes cluster (Flannel CNI); public game
traffic uses a MetalLB UDP address pool (one `LoadBalancer` Service per server); the control plane is
Python / Flask (served by Gunicorn), driving the cluster via the official Kubernetes Python client;
the custom game-server image lives in `harbor.irulast.com`; secrets come from OpenBao.

## Development Workflow

Work follows the Spec Kit spec-driven flow, seeded by the documents in `docs/`:
`/constitution` → `/specify` → `/plan` → `/tasks` → `/implement`. Specs describe user-observable
behavior; technology and architecture choices live in the plan, not the spec. Build order validates
the riskiest pieces first (MetalLB UDP exposure, RCON, then the payment + Steam-auth loop) before
broadening.

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

**Version**: 2.1.0 | **Ratified**: 2026-07-09 | **Last Amended**: 2026-07-13
