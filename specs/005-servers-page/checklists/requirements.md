# Specification Quality Checklist: The Servers Page

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-07-29
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

- Items marked incomplete require spec updates before `/speckit-clarify` or `/speckit-plan`.

### Validation iteration 1 (2026-07-29)

**Failing**: "No [NEEDS CLARIFICATION] markers remain" — 3 markers open (Q1 scope, Q2 entitlement
unit, Q3 operator surface). All three are scope-level and lack a defensible default:

- **Q1** decides whether this is a presentation-layer feature or the provisioning feature the
  constitution names as the riskiest unproven piece. The two produce very different plans.
- **Q2** is recorded in the constitution's own Sync Impact Report as a follow-up TODO that MUST be
  settled "before the first provisioning feature is specified". It changes the request UX materially.
- **Q3** determines whether an operator mode belongs on this page or is its own feature.

Awaiting user answers; no other checklist item is failing.

### Validation iteration 2 (2026-07-29, after `/speckit-clarify`)

**All 16 items passing.** Five questions asked and answered; the two markers that were not put to the
user (entitlement unit, operator surface) were resolved by implication of the answers given and are
recorded in Clarifications rather than left open.

**Fixed during iteration 2**:

- FR-034 named OpenBao directly; softened to "the platform's secret store" so the spec stays
  technology-agnostic and the plan chooses the mechanism.
- SC-014 referred to "Steam's trade API"; reworded to "the payment provider's systems".
- FR-014 and FR-019 still described an operator approve/decline step that the chosen payment mechanism
  removes; both rewritten around payment-driven states.
- FR-021 forbade storing "payment details", which the Accounts-page trade link would have contradicted;
  narrowed to card and bank details, with the trade link explicitly identified as an account identifier.

**Recorded as assumptions, not decisions** (worth confirming before implementation):

- Extensions are priced at double rate — a credit buys 60 minutes up front but 30 on an extension.
- The runtime window starts when the server is ready, not at the scrim's scheduled time.
- Credits convert as `floor(keys × 2.5)`, avoiding fractional remainders.
- The grace period is granted once per server rather than once per extension; the alternative would let
  repeated extension accumulate free time.

**Fixed during iteration 1**:

- Success criteria were reworded to drop technical phrasing (e.g. "no server renders in an
  unexplained or blank state" rather than referencing response payloads).
- Added the single-team assumption, which several acceptance scenarios silently relied on.
- Removed a stray reference to how times are rendered from the requirements into Assumptions, keeping
  FRs free of presentation mechanics.
