# Constitution Seed — TF2 Server Hosting

> **Purpose of this file.** Starting principles that seeded Spec Kit's **`/constitution`**
> step. The authoritative, current principles live in
> [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) (currently
> **v3.0.0** — a free scrim scheduling platform for competitive TF2 teams, with paid dedicated
> servers attached to the scrims they schedule; payment handled out-of-band by the operator, who
> records the approval). This file is kept in sync as a readable summary.

## Principles

1. **Scrims first, servers as the upsell.** The loop to prove is Steam login → link an RGL
   identity → find or arrange a scrim → optionally pay to have a server ready when it starts.
   Scheduling is **free and complete on its own**: a team that never pays a cent can still post
   listings, claim them, propose matches, see rosters, and track attendance. Paid work attaches to
   a scrim that already exists rather than standing in front of it. Prefer the smallest thing that
   works over the most general thing.

2. **Servers are cattle, not pets.** Every granted server is fully described by code + config,
   is bound to its entitlement, and is disposable. Two lifecycles are in scope — **per-scrim**
   (created shortly before its scrim's scheduled start, destroyed once the match ends) and
   **season term** (suspend → grace → delete). Creating and destroying one is routine and leaves
   no orphaned cluster resources (workload, service, PVC, MetalLB IP).

3. **Kubernetes-native control.** The control plane manipulates the cluster through its API
   (the Kubernetes Python client), not by shelling out to `kubectl`. State lives in k8s
   objects and the metadata store, not in an operator's head.

4. **Secure by default.** A Steam-verified identity plus a linked RGL identity is the account,
   and team authority is re-checked server-side against stored memberships — never inferred from
   submitted ids. No server reachable without an RCON password; RCON never exposed to players;
   secrets from OpenBao, never hardcoded or logged. **Payments:** the app never processes or
   stores payment/card data — payment is handled out-of-band by the operator, and compute is
   granted only by an explicit, recorded operator approval verified server-side.

5. **Reproducible images.** The game-server image is built from a pinned SteamCMD / SourceMod
   recipe and pushed to `harbor.irulast.com`. Rebuilds are deterministic; no manual mutation
   of running containers.

6. **Everything as code.** Cluster manifests, image builds, and config templates live in this
   repo under version control. Changes go through the repo, not by hand on the cluster.

7. **Right-size the blast radius.** Every server has enforced CPU/memory limits and quotas so
   one tenant can't starve the node or the cluster. Because scrims cluster into evenings, the
   number of servers auto-started concurrently is bounded, and a scheduled scrim whose server
   can't be placed fails visibly to its team rather than silently degrading the cluster. Because
   servers are publicly sold and joined, DDoS resilience, abuse controls, and GSLT for public
   listing are first-class concerns — not deferred.

8. **Free to schedule, approved to provision.** Users sign in with Steam OpenID and link an RGL
   identity; that verified pair gets the full scrim surface — listings, proposals, claims, rosters,
   attendance, opponent discovery — at no charge. Compute is the paid tier: no server is
   provisioned, started, or kept running without an **operator-approved entitlement** — a
   **per-scrim server** for one scheduled match or a **season term** for a rented server (the
   operator approves after handling payment out-of-band). The requester (team captain)
   individually owns the server they are granted; an auto-started server is bound to a specific
   scheduled scrim, owned by the team that scheduled it, and must not outlive its entitlement:
   per-scrim → destroyed after the match; season → suspend → grace (retain config) → delete &
   reclaim. The concrete unit granted for a per-scrim server (a single credit vs. a bundle) is
   **not yet decided**.

## Non-goals (this phase)

In-app/automated payment processing · recurring/hourly billing · in-app role hierarchies beyond
RGL membership (plus the creator of a listing) · notifications and reminders · SLAs · multi-region ·
games other than TF2.
