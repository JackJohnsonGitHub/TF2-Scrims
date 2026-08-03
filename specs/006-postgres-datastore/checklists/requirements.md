# Specification Quality Checklist: Durable Multi-Writer Metadata Store

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-30
**Feature**: [spec.md](../spec.md)

## Content Quality

- [x] No implementation details (languages, frameworks, APIs)
- [x] Focused on user value and business needs
- [x] Written for non-technical stakeholders
- [x] All mandatory sections completed

## Requirement Completeness

- [x] No [NEEDS CLARIFICATION] markers remain
- [x] Requirements are testable and unambiguous
- [x] Success criteria are measurable
- [x] Success criteria are technology-agnostic (no implementation details)
- [x] All acceptance scenarios are defined
- [x] Edge cases are identified
- [x] Scope is clearly bounded
- [x] Dependencies and assumptions identified

## Feature Readiness

- [x] All functional requirements have clear acceptance criteria
- [x] User scenarios cover primary flows
- [x] Feature meets measurable outcomes defined in Success Criteria
- [x] No implementation details leak into specification

## Notes

### Validation iteration 1 — 2026-07-30

**Passing with one deliberate exception**, plus one judgement call worth recording.

**Judgement call — "No implementation details": PASS, with a named exception.**
The feature's input is itself a technology directive ("use Postgres"), which sits in
tension with the project constitution's rule that *"technology and architecture choices
live in the plan, not the spec"* (Development Workflow). Resolved by:

- Naming PostgreSQL **once**, in Assumptions, explicitly flagged as a directed constraint
  rather than a derived conclusion.
- Writing every FR and SC as an outcome verifiable without knowing the store's identity —
  concurrent writers (FR-011), exactly-once crediting (FR-012), referential integrity
  (FR-014), multiple app copies (FR-017), restore (FR-021), ordered schema changes
  (FR-022).
- Keeping *where and how* Postgres runs — in-cluster vs managed, connection pooling,
  driver, migration tool — entirely for `/plan`.

The consequence is that this spec stays honest under a change of engine: if `/plan`
concluded some other store served these requirements better, the spec would not need
rewriting. That is the test the exception was designed to pass.

The Overview also describes the *current* store's shape (one file, one disk, one
instance). This is problem statement, not implementation direction, and is needed for a
reader to understand why the feature exists at all.

**Failing item — [NEEDS CLARIFICATION] markers remain: 2 open.**
Both are scope-level and were judged not to have a defensible default:

- **CL-001** — migrate existing data, or start empty. Roughly half the feature's surface
  (US1, FR-004–FR-010, SC-001, SC-007) hangs on the answer. Evidence points both ways:
  a populated local store exists, but `deploy/deployment.yaml` still carries a
  `REPLACE-ME` hostname, which suggests the platform has never served real users.
  Guessing wrong in the "start empty" direction risks destroying a credit ledger the
  constitution requires be explainable — too costly to assume.
- **CL-002** — one store everywhere, or keep the old one for tests. Determines whether
  every query must remain valid in two dialects indefinitely (~80 call sites across 8
  application modules and 26 test files). A permanent structural cost, not a detail.

A third candidate — downtime tolerance during cutover — was **not** marked. A scheduled
maintenance window outside scrim hours is a reasonable default and is recorded in
Assumptions instead.

**Status**: blocked on CL-001 and CL-002. Every other item passes. Once both are
answered, the affected sections are updated, this checklist is re-run, and the spec is
ready for `/speckit-plan`.

### Validation iteration 2 — 2026-07-30

**16/16. Both blockers resolved; the spec is ready for planning.**

`/speckit-clarify` answered CL-001 and CL-002 in the same session, and both answers are
recorded in the spec's Clarifications section:

- **CL-001 → start empty.** Verified against the current store rather than assumed: 2
  accounts (one the seeded demo rival), 3 credit ledger entries whose first reads "Manual
  grant for local testing (no payment)", and 2 payments both `failed` with no provider
  reference. Gitignored, never deployed. The dependent surface (FR-004–FR-007, SC-008,
  Out of Scope) was rewritten from "migrate" to "replace".
- **CL-002 → one engine everywhere.** No dual-dialect support, no compatibility layer.
  Recorded in FR-025 and Out of Scope, with the cost accepted explicitly: running the
  suite now requires a local store, in exchange for tests that exercise the same
  integrity guarantees the deployment relies on.

`grep -n "NEEDS CLARIFICATION" spec.md` returns nothing. The judgement call from
iteration 1 — naming PostgreSQL once, in Assumptions, as a directed constraint — stands
unchanged and was not affected by either answer.

**Status**: passing. `/speckit-plan` completed against this spec on 2026-07-30.
