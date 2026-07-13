# Technical Context — TF2 Server Hosting

> **Purpose of this file.** Captures the technology decisions, target
> environment, and known-hard problems so they survive until Spec Kit's
> **`/plan`** step. This is *not* the spec — keep user-facing behavior in
> [`product-brief.md`](product-brief.md). Think of this as the constraints and
> raw material `/plan` should consume.

## Target environment

- **Cluster:** `mke` — Irulast's bare-metal Kubernetes cluster, Flannel CNI,
  managed by the `bare-metal-k8s-setup` Ansible repo. No cloud load balancer.
- **Access:** internal hosts generally require the WireGuard tunnel up.
- **Registry:** `harbor.irulast.com` for the custom game-server image.
- **Secrets:** OpenBao at `https://secrets.irulast.com` — pull RCON passwords /
  tokens from there, never hardcode.

## Component overview

```
   Steam OpenID ◀──┐                 Operator (out-of-band payment)
   (sign in)       │                        │ approves request
                   │ HTTPS                  ▼
        Browser (captain/owner) ───▶ [ server request ] ──▶ approval
            │  HTTPS
            ▼
   ┌─────────────────────┐    k8s python client  ┌──────────────────────┐
   │   Control plane     │ ───────────────────▶  │   mke k8s API        │
   │   (Python / Flask)  │                        └──────────────────────┘
   │                     │                          │ creates (only if approved)
   │  - REST API + web   │                          ▼
   │  - Steam auth       │          ┌─────────────────────────────┐
   │  - requests/approve │          │  Per-server workload         │
   │  - RCON relay ──────┼─ 27015 ─▶│  SRCDS (TF2, app 232250)     │
   │  - metadata store   │          │  + MetaMod/SourceMod         │
   └─────────────────────┘          │  PVC: server.cfg, maps       │
        MetalLB UDP LoadBalancer ◀─▶│  (bound to approved term)    │
        (public IP : 27015 UDP)     └─────────────────────────────┘
                    ▲
              Players (TF2 client)
```

## Decisions

### Control plane / API — Python / Flask
- **Flask** serves both the HTTP API and the server-rendered web UI (owner-directed;
  see Constitution v1.1.0). Served in the container by **Gunicorn** (the Flask dev
  server is not used in production).
- **Official Kubernetes Python client** to drive the cluster — create/patch/delete the
  per-server workloads and their services via the API rather than shelling out to
  `kubectl`.
- **Metadata store** for users (Steam identities), server requests + approvals, and server
  records: start with SQLite (single node); leave room to move to Postgres. (Not yet
  present — the 001 scaffold has no persistence.)
- **Web frontend** — server-rendered Jinja templates + a single stylesheet, kept
  minimal (no SPA/JS build toolchain).

### Authentication — Sign in with Steam (OpenID)
- Users authenticate via **Steam's OpenID 2.0** provider; the verified 64-bit SteamID
  is the account identity. No passwords are stored by us.
- A server-side session (signed cookie) is established after Steam returns; the session
  key and any Steam Web API key come from **OpenBao**.
- The **buyer (captain) is the individual owner** of the servers they purchase — no
  multi-member team accounts or roles yet (out of scope this phase).

### Access — server request + operator approval (payment out-of-band)
- A signed-in captain submits a **server request** (desired settings + term). A server is
  provisioned **only after the operator approves** that request. The app **never processes
  or stores payment/card data** — payment is arranged out-of-band; approval is the gate.
- Model requests with a status (`pending` → `approved`/`declined`), an owner SteamID, the
  requested settings, and (on approval) a term start/end. Approval is performed by the
  operator through an operator-only view; the approved record is authoritative and enforced
  **server-side** (never inferred from client input).
- A **lifecycle reaper** enforces the term: at term end → **suspend** the workload → keep
  the PVC through a **grace period** for renewal → **delete & reclaim** (workload, Service,
  PVC, MetalLB IP).

### One rented server = one k8s workload
- Container image: **SteamCMD-installed TF2 dedicated server** (Steam app
  `232250`), with **MetaMod + SourceMod** baked in for admin plugins. Built and
  pushed to `harbor.irulast.com`.
- Model each server as a `StatefulSet` (stable identity + one PVC) or a
  `Deployment` + PVC — decide in `/plan`. One **PVC per server** holds `server.cfg`,
  downloaded maps, and SourceMod config so it survives restarts.
- Enforce CPU/memory **resource limits** per pod so one server can't starve the node.

### Public networking — MetalLB UDP pool
- TF2 is **UDP**; players connect directly to `IP:port`. On bare-metal there is no
  cloud LB, so use **MetalLB** with a dedicated **UDP address pool**.
- Each server gets its own `LoadBalancer` Service exposing:
  - **27015/UDP** — game traffic
  - **27020/UDP** — SourceTV (optional)
  - **27015/TCP** — RCON (used by the control plane's relay, not exposed to players)
- **Prerequisite:** confirm MetalLB is installed on `mke` and reserve a usable
  public IP range for the pool. If not present, that's an early setup task
  (coordinate via `bare-metal-k8s-setup`).

### RCON (from the BisectHosting guide)
- RCON speaks the **Source RCON protocol over TCP on the game port (`27015`)**.
- Enable it by setting **`rcon_password`** in the server's `server.cfg`. Harden with
  the `sv_rcon_*` cvars (`sv_rcon_maxfailures`, `sv_rcon_banpenalty`,
  `sv_rcon_minfailuretime`, and an address whitelist).
- The control plane's **RCON relay** uses a Python RCON client to connect pod-side
  and forward commands from the web console. RCON is **never exposed publicly** —
  only the control plane talks to it.
- Generate a strong `rcon_password` per server, store it in OpenBao, template it
  into `server.cfg` at provision time, and surface/rotate it via the API.

### Config templating
- `server.cfg` is generated per server from the owner's settings (hostname, starting
  map, `maxplayers`, `sv_password`, `rcon_password`) and written to the PVC before
  the container starts.

## Known-hard problems (flag these in `/plan`)

1. **UDP on bare-metal** — MetalLB UDP pool + unique public address per server is
   the riskiest piece; validate it in isolation first.
2. **Approval integrity** — provision strictly on a server-side operator approval; guard
   against a client granting itself a server, double-provisioning, and approval races.
3. **Season lifecycle** — the expiry reaper must reliably suspend → grace → delete
   without leaking resources or deleting a server whose owner just renewed.
4. **Steam GSLT** — a publicly-*listed* server needs a Game Server Login Token; since
   servers are now publicly sold, decide GSLT provisioning early (per-server vs pool).
5. **Image size / boot time** — TF2 game files are large; bake them into the image
   (or a warm cache) so "purchase → joinable" stays near ~1 minute.
6. **Orphan cleanup** — ensure delete reclaims the workload, service, PVC, and the
   MetalLB IP.
7. **DDoS** — now in scope (competitive servers are targets); plan rate/abuse controls
   and consider upstream filtering for the UDP pool.

## Suggested build order (for `/tasks`)

1. **Sign in with Steam** — OpenID login + session + user records (identity foundation).
2. Build + push the TF2 SRCDS container image; run it once by hand on `mke`.
3. Prove MetalLB UDP exposure: one server, one public IP, join from a real client.
4. Prove RCON: connect from a Python RCON client, run `status` / `changelevel`.
5. **Server request + operator approval** — request form, operator review/approve view,
   request/approval records (payment handled out-of-band).
6. Control-plane provisioning: create a server **only for an approved request** (drives
   k8s via the Kubernetes Python client); list/delete.
7. Web UI over the API + the RCON web console; server term status + renewal request.
8. Lifecycle reaper: suspend → grace → delete at term end.
