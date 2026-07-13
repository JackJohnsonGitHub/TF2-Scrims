# Constitution Seed — TF2 Server Hosting

> **Purpose of this file.** Starting principles that seeded Spec Kit's **`/constitution`**
> step. The authoritative, current principles live in
> [`.specify/memory/constitution.md`](../.specify/memory/constitution.md) (currently
> **v2.1.0** — a paid service for competitive TF2 teams; payment handled out-of-band by the
> operator via a server-request + approval model). This file is kept in sync as a readable summary.

## Principles

1. **Ship the smallest paid loop first.** Prove the core loop (Steam login → request a server →
   operator approves, payment out-of-band → joinable, RCON-manageable server → auto-expire/teardown)
   before building anything else. Prefer the smallest thing that works over the most general thing.

2. **Servers are cattle, not pets.** Every rented server is fully described by code + config,
   is bound to its approved term, and is disposable. Creating and destroying one is routine
   and leaves no orphaned cluster resources (workload, service, PVC, MetalLB IP).

3. **Kubernetes-native control.** The control plane manipulates the cluster through its API
   (the Kubernetes Python client), not by shelling out to `kubectl`. State lives in k8s
   objects and the metadata store, not in an operator's head.

4. **Secure by default.** Steam-verified identity for accounts; no server reachable without an
   RCON password; RCON never exposed to players; secrets from OpenBao, never hardcoded or
   logged. **Payments:** the app never processes or stores payment/card data — payment is handled
   out-of-band by the operator, and access is granted only by an explicit, recorded operator
   approval verified server-side.

5. **Reproducible images.** The game-server image is built from a pinned SteamCMD / SourceMod
   recipe and pushed to `harbor.irulast.com`. Rebuilds are deterministic; no manual mutation
   of running containers.

6. **Everything as code.** Cluster manifests, image builds, and config templates live in this
   repo under version control. Changes go through the repo, not by hand on the cluster.

7. **Right-size the blast radius.** Every server has enforced CPU/memory limits and quotas so
   one tenant can't starve the node or the cluster. Because servers are publicly sold and
   joined, DDoS resilience, abuse controls, and GSLT for public listing are first-class
   concerns — not deferred.

8. **Steam-authenticated, approved access.** Users sign in with Steam OpenID; the requester (team
   captain) individually owns the server they are granted. To get a server a signed-in user submits a
   **server request**; no server is provisioned, started, or kept running without an
   **operator-approved request** (the operator approves after handling payment out-of-band). At term
   end the server follows suspend → grace (retain config) → delete & reclaim.

## Non-goals (this phase)

In-app/automated payment processing · recurring/hourly billing · multi-member team accounts & roles ·
free tier · SLAs · multi-region · games other than TF2.
