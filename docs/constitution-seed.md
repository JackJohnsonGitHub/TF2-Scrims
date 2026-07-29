# Constitution Seed — TF2 Server Hosting

> **Purpose of this file.** Starting principles that seeded Spec Kit's **`/constitution`**
> step. The authoritative, current principles live in
> [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) (currently
> **v3.1.0** — a free scrim scheduling platform for competitive TF2 teams, with paid dedicated
> servers attached to the scrims they schedule; paid for in **credits** worth an hour of runtime
> each, bought out-of-band and granted when the operator accepts the payment). This file is kept
> in sync as a readable summary.

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
   provisioned, started, or kept running without **credits** the operator has granted. **A credit
   is one hour of server runtime** — the entitlement unit, settled in v3.1.0. Credits are reserved
   when a server is attached to a scheduled scrim, consumed as it runs, returned if it never ran,
   and cost one credit per 30 minutes to extend. Payment happens out-of-band; the operator
   accepting it **is** the granting act, and the platform observes the completed payment rather
   than taking a client's word for it. The first payment method is a **Steam trade offer** (2 Mann
   Co. Supply Crate Keys → 5 credits); more are planned, so the entitlement model stays
   method-agnostic. The requester (team captain) individually owns the server they are granted; an
   auto-started server is bound to a specific scheduled scrim, its window starts at that scrim's
   scheduled time, and it must not outlive its credits: per-scrim → stopped and reclaimed once its
   window plus a single 15-minute unpaid grace elapses; season → suspend → grace (retain config) →
   delete & reclaim. The **season-term** purchase unit is still undecided.

## Non-goals (this phase)

In-app/automated payment processing · recurring/hourly billing · in-app role hierarchies beyond
RGL membership (plus the creator of a listing) · notifications and reminders · SLAs · multi-region ·
games other than TF2.
