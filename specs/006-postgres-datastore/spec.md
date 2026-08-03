# Feature Specification: Durable Multi-Writer Metadata Store

**Feature Branch**: `006-postgres-datastore`

**Created**: 2026-07-30

**Status**: Draft

**Input**: User description: "I would Like to use Postgres instead of sql as itll be better to use in the long run"

## Overview

Everything the platform knows lives in one metadata store: who signed in, which RGL
identity they linked, every scrim posted or claimed, who attended, every payment
observed, every credit granted or spent, and every server issued. Today that store is a
single file on a single disk attached to a single running copy of the app.

That shape is now the binding constraint on the platform, and in three distinct ways:

1. **One instance, therefore downtime.** The file's volume can only be attached to one
   node at a time, so exactly one copy of the app can run. Every deploy is an outage, and
   scrims cluster into weekday evenings — the worst possible time to take the scheduling
   surface away.
2. **Writers already contend.** The payment poller and the server reconciler run as
   separate processes from the web app, all writing the same file. Contention is handled
   today by making writers *wait* on each other; under load, waiting becomes failing, and
   the request that fails may be the one crediting somebody's payment.
3. **No recovery story.** There is no way to restore the store to a known good point.
   For scrim history that is an annoyance. For the credit ledger — which the constitution
   requires be able to explain a disputed balance without the operator's help — it is a
   liability.

This feature replaces the store with one that supports concurrent writers and multiple
app instances, and gives the operator a real backup and restore path. The platform has
never served real users, so **no data is carried across** — the new store starts empty.
**No user-facing behavior changes.** Every screen, rule, and permission behaves exactly
as it does today; what changes is that the platform stops falling over when two things
happen at once.

## Clarifications

### Session 2026-07-30

- Q: Must existing data be migrated, or is starting from an empty store acceptable? → A: Start empty. The current store holds only local test data — 2 accounts (one of them a demo rival), 3 credit ledger entries whose first reads "Manual grant for local testing (no payment)", and 2 payments both in `failed` state with no provider reference. It is gitignored and has never been deployed. Dev and demo state is rebuilt with the existing seed script; cached RGL data repopulates from the RGL API on demand.
- Q: Must the previous store stay supported for local development and tests, or is the new store the only one everywhere? → A: One store engine everywhere — development, automated tests, and deployment. No dual-dialect support. Running the test suite therefore requires a local store, accepted in exchange for tests that exercise the same integrity guarantees the deployed platform relies on.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Concurrent writes stop failing (Priority: P1)

It is 8pm on a Sunday. Eighteen players are loading scrim pages, the payment poller is
crediting a trade that just completed, and the reconciler is stopping a server whose
window ran out. All of it succeeds. Nobody sees an error page, and the person who just
paid gets their credits.

**Why this priority**: This is the reason the current store is the constraint rather than
merely inelegant, and the failure mode it removes is silent and money-adjacent: a credit
grant that loses a write does not look broken from the outside — it looks like a payment
that never arrived. Delivering this story necessarily delivers the whole store
replacement, which makes it the smallest slice that stands on its own.

**Independent Test**: Drive concurrent page loads against the platform while running the
payment poller and the reconciler simultaneously against the same store, and confirm
zero requests fail from store contention and every write lands exactly once.

**Acceptance Scenarios**:

1. **Given** the payment poller is mid-write crediting an account, **When** a team
   captain loads their dashboard, **Then** the page renders normally rather than
   erroring or hanging.
2. **Given** two processes attempt to credit the same completed payment at the same
   moment, **When** both finish, **Then** the account is credited exactly once and the
   ledger contains exactly one entry for that payment.
3. **Given** a server's runtime window expires while its team is viewing the server
   page, **When** the reconciler stops it, **Then** neither the reconciler's write nor
   the page load fails.
4. **Given** sustained concurrent use across the whole scrim surface, **When** the
   session ends, **Then** no request has failed because the store was busy.

---

### User Story 2 - The operator can recover the platform (Priority: P2)

The disk holding the platform's data is lost. The operator restores from a backup, and
the platform comes back with accounts, scrims, and — critically — every credit and every
ledger entry explaining how balances got where they are.

**Why this priority**: The constitution requires that a disputed balance be explainable
without the operator's help. That guarantee is only as good as the operator's ability to
get the ledger back. It ranks below P1 because it addresses a rarer event, but it is the
difference between an incident and an unrecoverable one.

**Independent Test**: Take a backup, destroy the store, restore from that backup, and
verify the platform returns to service with the backed-up data intact and correct
balances.

**Acceptance Scenarios**:

1. **Given** a backup taken at a known time, **When** the operator restores it onto a
   fresh store, **Then** the platform serves requests with all data as of that time.
2. **Given** a restored store, **When** any user opens their credit page, **Then** their
   balance equals the sum of their restored ledger entries.
3. **Given** backups are running on their schedule, **When** the operator inspects them,
   **Then** they can see when the last successful backup completed and confirm it is
   recent.

---

### User Story 3 - Deploys stop being outages (Priority: P3)

The operator ships a change on a Tuesday evening. Teams browsing listings and proposing
scrims at that moment notice nothing — no error page, no interruption.

**Why this priority**: The direct payoff of a store that several app copies can share.
It ranks last only because it is the one story that delivers no correctness guarantee —
but it is what makes the platform safe to work on during the hours teams actually use it.

**Independent Test**: Run more than one copy of the app against the same store, issue a
rolling deploy under continuous traffic, and confirm no request fails.

**Acceptance Scenarios**:

1. **Given** more than one copy of the app is serving, **When** one is restarted, **Then**
   requests continue to be served without error by the others.
2. **Given** a signed-in user is served by one copy, **When** their next request is
   served by a different copy, **Then** they remain signed in and see the same data.
3. **Given** several copies start at once against an empty store, **When** they all
   initialise it, **Then** the store ends up correctly initialised exactly once and no
   copy fails to start.

---

### Edge Cases

- **The store is unreachable.** At startup and mid-request, an unreachable store must
  fail visibly — a clear error and a failed readiness check — rather than serving pages
  that appear to work but silently show nothing.
- **A brief connection interruption.** A momentary network blip between app and store
  must not require an operator to restart anything.
- **Several app copies initialise at once.** Two copies starting simultaneously against
  an empty store must not race into a broken or half-created schema, and neither may
  fail to start because the other won.
- **The RGL cache starts cold.** Starting empty discards the cached league directory, so
  the first opponent-discovery browse after cutover finds no known teams and must
  repopulate within its existing per-request hydration bound rather than stalling, timing
  out, or presenting an empty directory as if the league had no teams.
- **The old store is left behind.** A leftover database file or its volume must not
  remain reachable to any running process, or the platform could silently read stale
  state from a store nobody is writing to.
- **A running server at cutover.** A server mid-window when the platform is cut over must
  not have its runtime window restarted or its credits re-charged when the platform
  returns.

## Requirements *(mandatory)*

### Functional Requirements

#### Behavioral parity

- **FR-001**: The platform MUST behave identically to its pre-migration self across
  every existing surface — sign-in, RGL linking, dashboard, listings, proposals, claims,
  rosters, attendance, opponent discovery, payments, credits, and servers. This feature
  introduces no new user-facing capability and removes none.
- **FR-002**: All existing authority rules MUST continue to be enforced server-side and
  unchanged, including who may join a scrim's server versus who may control it.
- **FR-003**: The complete existing automated test suite MUST pass against the new store,
  with test expectations unchanged except where a test asserts a detail of the old store's
  mechanics rather than platform behavior.

#### Replacement, not migration

- **FR-004**: The new store MUST start empty, with its structure created from definitions
  held in this repository. No data is carried over from the previous store.
- **FR-005**: The previous store MUST be decommissioned as part of the cutover — its file
  and the volume holding it removed, and no running process left able to reach it — so it
  cannot survive as a second, stale source of truth.
- **FR-006**: A developer or operator MUST be able to rebuild demo and development data
  on an empty store from a documented, repeatable script, so an empty store is a usable
  starting point rather than a dead end.
- **FR-007**: Cached league data MUST repopulate on demand from the RGL API without
  operator action, and the platform MUST remain usable while that cache is still cold.

#### Integrity under concurrent writers

- **FR-008**: The store MUST support concurrent writers — the web app, the payment
  poller, and the server reconciler — without any of them failing or being made to wait
  indefinitely because another is writing.
- **FR-009**: A payment MUST grant credits exactly once no matter how many times it is
  observed or how many processes observe it simultaneously; this MUST be guaranteed by
  the store itself, not only by the code paths that call it.
- **FR-010**: At most one server MUST be attachable to any given scrim, enforced by the
  store even under simultaneous attempts.
- **FR-011**: Referential integrity MUST be enforced by the store for all records, so a
  ledger entry, attendance mark, or server cannot reference an account, scrim, or team
  that does not exist.
- **FR-012**: A credit grant and the payment state change that justifies it MUST commit
  together or not at all; the same MUST hold for a credit reservation and the server it
  reserves for.
- **FR-013**: An account's available credit MUST continue to be derived from its recorded
  ledger entries rather than a stored total, so a balance can never disagree with the
  history that explains it.

#### Availability and operations

- **FR-014**: More than one copy of the app MUST be able to serve from the same store
  simultaneously, with a signed-in session valid against any copy.
- **FR-015**: Store initialisation MUST be safe when several copies start at once —
  exactly one initialisation takes effect and no copy fails to start because it lost the
  race.
- **FR-016**: The platform MUST fail visibly when the store is unreachable — the
  readiness check MUST fail and the failure MUST be logged — rather than serving pages
  that appear normal but show nothing.
- **FR-017**: The store's data MUST be backed up on a schedule, and the operator MUST be
  able to see whether the most recent backup succeeded and when.
- **FR-018**: The operator MUST be able to restore the platform's data from a backup onto
  a fresh store and return the platform to service.
- **FR-019**: Schema changes MUST be applied by a repeatable, ordered mechanism recorded
  in the repository, so any environment can be brought to the current schema and future
  changes do not require hand-editing a live store.
- **FR-020**: Store credentials MUST come from OpenBao, MUST NEVER be committed to the
  repository, logged, or sent to any client.
- **FR-021**: All manifests and configuration needed to run and reach the store MUST live
  in this repository under version control.
- **FR-022**: The store MUST run under enforced CPU and memory limits so it cannot starve
  the node or other tenants of the shared cluster.
- **FR-023**: Every process that reaches the store MUST do so through a single shared
  access path, so connection settings, credentials, and integrity guarantees cannot drift
  between the web app and the background jobs.

#### Development and testing

- **FR-024**: A developer MUST be able to run the platform and its full test suite
  locally with a documented setup, without access to the production store or the cluster.
  Because that setup requires a running store, the suite MUST fail with a clear,
  actionable message when none is reachable, rather than an error that reads as a broken
  test.
- **FR-025**: The platform MUST support exactly one store engine, used unchanged across
  development, automated tests, and deployment. No second engine or compatibility layer
  may be maintained, so no query can be valid in one environment and invalid in another.
- **FR-026**: Automated tests MUST exercise the integrity rules in FR-008 through FR-013
  against that same engine, so a violation cannot pass tests and fail in production.
- **FR-027**: Each test MUST start from a clean, isolated state and MUST NOT be affected
  by data left behind by another test, including when tests share one local store.
- **FR-028**: The repository's documentation MUST be updated to describe the store the
  platform actually uses, including local setup, backup, and restore.

### Key Entities

This feature introduces **no new entities and changes no entity's meaning**. The
following existing entities are recreated in the new store; they are listed because its
structure must account for every one of them:

- **Account**: a Steam-verified identity — the platform's root record. Nearly every other
  entity references it.
- **RGL link, team, membership, roster, season**: the linked league identity and the
  cached league data that team authority is re-checked against.
- **Scrim**: a scheduled match between two teams, with its origin, status, and notes.
- **Attendance mark**: one player's status for one scrim.
- **Trade link**: a user's own trade URL, holding a token — secret-bearing, so it must not
  be exposed in logs, backups, or any client-facing surface.
- **Payment**: one attempt to pay by any method, carrying the provider reference whose
  uniqueness is the exactly-once guarantee for crediting.
- **Credit ledger entry**: an append-only record of one movement of credit with its
  cause. The authoritative history behind every balance; the entity with the least
  tolerance for loss or reordering.
- **Server**: a server a team is entitled to, with its state, runtime window, grace, and
  join details — and deliberately without any administrative password.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the existing automated test suite passes against the new store.
- **SC-002**: Under sustained concurrent use — at least 20 simultaneous users plus the
  payment poller and reconciler running — zero requests fail due to store contention,
  against a baseline where such failures are possible today.
- **SC-003**: Replaying the same completed payment at least 10 times, including from
  processes running simultaneously, results in exactly one credit grant and exactly one
  ledger entry.
- **SC-004**: A deploy performed under continuous traffic causes zero failed requests,
  compared with a guaranteed interruption today.
- **SC-005**: The operator can restore the platform to a state no more than 24 hours old
  and return it to service within 30 minutes, verified by rehearsal at least once.
- **SC-006**: A developer can go from a fresh clone to a passing test suite by following
  the documented setup — including standing up a local store — in under 15 minutes.
- **SC-007**: No user-visible behavior changes: a walkthrough of every existing screen
  before and after the cutover produces identical results.
- **SC-008**: After cutover the platform serves entirely from the new store, with the
  previous store's volume removed and zero processes still configured to reach it.

## Assumptions

- **Directed technology choice.** The operator has directed that the store be
  **PostgreSQL**. This is recorded here as a given constraint rather than derived from the
  requirements above; the requirements are written so they can be verified as outcomes
  regardless. Where and how Postgres is run is a `/plan` decision, not a spec one.
- **The requirements above are what "better in the long run" means.** The user's stated
  reason is longevity; concurrent writers, multiple app copies, real backups, and ordered
  schema changes are taken to be the substance of that.
- **No new product capability.** This feature is a foundation change. It deliberately
  does not add features, and does not resolve the constitution's open question about the
  season-term purchase unit.
- **Nothing of value is lost by starting empty.** Confirmed against the current store: it
  holds test accounts and a self-granted test ledger only, is gitignored, and has never
  been deployed to real users.
- **The platform is not yet serving production traffic**, so the cutover itself may take
  a brief planned interruption — for this cutover only, not as ongoing practice
  (see FR-014 and User Story 3).
- **Scale is modest.** Sizing targets low hundreds of teams and a few thousand accounts;
  this feature is about correctness and availability under concurrency, not throughput.
- **The cluster can host the store.** The target `mke` cluster can run a database
  workload with persistent storage and can back it up.
- **Developers can run a local store.** Every developer's machine can run the store
  engine locally (a container is sufficient), which is what makes the single-engine
  decision affordable.

## Dependencies

- **OpenBao** at `secrets.irulast.com` for store credentials (Principle IV).
- **The `mke` cluster** for hosting the store, its storage, and its backups.
- **The repository** as the only route by which the store's configuration reaches the
  cluster (Principle VI).
- **The RGL API** to repopulate the league cache after the empty start (FR-007).
- **Feature 005's payment and credit model**, whose exactly-once and ledger guarantees
  this feature must carry across unchanged.

## Out of Scope

- **Migrating existing data** — the new store starts empty by decision (see
  Clarifications). No migration tooling, reconciliation, or rollback-to-old-store path is
  built.
- Any change to user-facing behavior, screens, or permissions.
- New product features, including the undefined season-term purchase unit.
- Multi-region or geographically replicated data.
- Automatic failover of the store; recovery is an operator action (FR-018).
- Analytics, reporting, or read replicas.
- **Supporting more than one store engine** — no compatibility layer, dialect abstraction,
  or fallback backend for tests or local development (see Clarifications, FR-025).
- Anything other than the metadata store — game-server volumes, images, and cluster state
  are untouched.
