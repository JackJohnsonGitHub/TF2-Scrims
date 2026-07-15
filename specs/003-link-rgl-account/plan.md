# Implementation Plan: Link RGL Account & Schedule Scrims

**Branch**: `003-link-rgl-account` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-link-rgl-account/spec.md`

## Summary

Extend the app (features 001/002) with competitive team identity and scrim scheduling. A signed-in
user **links their RGL account** — auto-detected from their verified Steam ID via RGL's public API —
which stores their profile and current team(s) per format. Two RGL-linked teams can then **schedule a
scrim** two ways: a directed **propose → accept/decline**, or an **open listing → claim**. Confirming
a scrim records the match (two teams, format, date/time, status) — it does **not** provision a server
(schedule-only; Principle VIII). No new secrets or dependencies; RGL data is public.

## Technical Context

**Language/Version**: Python 3.12 (extends the 001/002 app)

**Primary Dependencies**: Flask + Jinja2, `requests` (already present from 002 — reused for the RGL
API), Gunicorn. **No new dependencies.**

**Storage**: SQLite (extends the 002 store) with new tables: `rgl_links`, `rgl_teams`,
`rgl_memberships`, `scrims`. Accessed via thin data-access modules (same stdlib-`sqlite3` seam as 002).

**Testing**: pytest + Flask test client. The **RGL API is mocked** in tests (like Steam), covering
link/refresh/unlink, the scrim state machine (both creation paths, accept/decline/claim/cancel),
same-format enforcement, and team-authority checks.

**Target Platform**: same container on `mke`. New runtime need: outbound HTTPS to `api.rgl.gg`
(read-only, public — **no API key**).

**Project Type**: Web application (extends the single server-rendered Flask app).

**Performance Goals**: link + show teams < 10 s (SC-001); propose→accept round trip < 2 min of user
time (SC-003). RGL calls are on link/refresh only (not per page load).

**Constraints**: RGL calls MUST time out and degrade gracefully (FR-006/SC-008); all scheduling
actions are owner-only **and** gated on RGL-link + team membership (FR-008/FR-016); scrims are
same-format only (FR-012); confirming a scrim MUST NOT touch servers/payment (FR-018); scrim times
stored unambiguously (UTC), shown local.

**Scale/Scope**: a small competitive community; tens of teams, hundreds of scrims — trivial for SQLite.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against Constitution v2.1.0:

| Principle | Status | Notes |
|---|---|---|
| I. Ship the Smallest Paid Loop First | ⚠️ **Deviation — justified below** | Scrim scheduling is **work outside the core paid loop** (Steam→request→approval→server→expire), and that loop is **not yet proven** (request/approval/provisioning are unbuilt). Building 003 now is a user-directed sequencing choice — see Complexity Tracking. |
| II. Servers Are Cattle, Not Pets | ✅ N/A | No servers touched (schedule-only, FR-018). |
| III. Kubernetes-Native Control | ✅ N/A | No cluster mutation. |
| IV. Secure by Default | ✅ Pass | No new secrets (RGL public, keyless — verified); actions owner-only + membership-gated; no payments. |
| V. Reproducible Images | ✅ Pass | No new deps; image build unchanged/deterministic. |
| VI. Everything as Code | ✅ Pass | Schema + templates + routes in-repo. |
| VII. Right-Size the Blast Radius | ✅ Pass, with note | No per-tenant compute. New **external dependency** (api.rgl.gg) is called only on link/refresh, with timeouts + graceful failure. |
| VIII. Steam-Authenticated, Approved Access | ✅ Pass | Scrims never grant paid access or provision servers (FR-018); RGL link is identity enrichment only. |

**Result**: PASS with one **explicitly justified deviation** (Principle I sequencing) — see Complexity
Tracking. Recommend the user consciously accept the sequencing (or re-prioritize the paid loop first).

## Project Structure

### Documentation (this feature)

```text
specs/003-link-rgl-account/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   ├── rgl-routes.md     # Phase 1 — link/refresh/unlink
│   └── scrim-routes.md   # Phase 1 — scheduling routes + state machine
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root) — additions/changes

```text
app/
├── db.py                # CHANGED: add rgl_links, rgl_teams, rgl_memberships, scrims tables to schema
├── rgl.py               # NEW: RGL public API client — fetch_profile(steam_id) → profile + current teams
├── rgl_store.py         # NEW: persistence — link/refresh/unlink, get_link, teams for a user, get_team
├── scrims.py            # NEW: scrim data access + state machine (propose/accept/decline/withdraw,
│                        #      create_listing/claim/cancel) + queries + same-format & membership checks
├── routes/
│   ├── rgl.py           # NEW: GET account RGL section; POST /rgl/link, /rgl/refresh, /rgl/unlink
│   └── scrims.py        # NEW: scrims dashboard, propose, listings, and action endpoints (all guarded)
├── templates/
│   ├── account.html     # NEW/《or extend dashboard》: RGL link status + teams + manage
│   ├── scrims.html      # NEW: my scrims (incoming/outgoing pending, upcoming, my listings)
│   ├── scrim_new.html   # NEW: propose-a-scrim form (my team, opponent, date/time)
│   └── listings.html    # NEW: browse/claim open listings by format
└── ... (base.html nav gets RGL/Scrims links when signed in)

tests/
├── unit/
│   ├── test_rgl.py       # NEW: RGL profile parsing (mocked), no-profile/no-team/error fallbacks
│   └── test_scrims.py    # NEW: state machine transitions, same-format rule, past-date/self rejects
└── integration/
    ├── test_rgl_link.py  # NEW: link/refresh/unlink flow (mocked RGL), gating when unlinked
    └── test_scrims.py    # NEW: propose→accept/decline, listing→claim (first wins), cancel, authority
```

**Structure Decision**: Continue the single Flask app and stdlib-`sqlite3` seam from 002. Split RGL
protocol (`rgl.py`) from RGL persistence (`rgl_store.py`) and keep the scrim **state machine** in one
module (`scrims.py`) so the transition rules (and their guards) are testable in isolation. Teams are
first-class rows (`rgl_teams`) keyed by RGL's global team id, with `rgl_memberships` recording which
users may act for which team — this is what makes team-vs-team scheduling and the authority checks
(FR-016) work. Reuses `current_user`/`login_required` from 002; adds a small `rgl_link_required`
guard for scheduling actions (FR-008).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| **Principle I** — building scrim scheduling (003) before the core paid loop (server request → approval → provision) is proven | User has explicitly directed this feature now; RGL/team identity is the foundation the paid loop and team-aware features will reuse, and the clarified purpose (two teams scheduling scrims) is the product's near-term draw. Scheduling is **schedule-only** — it adds **no** billing or provisioning complexity, so it doesn't deepen the unproven part of the loop. | Doing the paid loop strictly first would defer what the user is actively asking for; it isn't "simpler," just a different order. The deviation is low-risk because 003 introduces no servers, secrets, or payments. **Recommendation:** either accept this sequencing consciously, or amend Principle I — do not let 003 crowd out finishing the request→approval→provision loop. |
