# Feature Specification: Sign in with Steam

**Feature Branch**: `002-steam-sign-in`

**Created**: 2026-07-13

**Status**: Draft

**Input**: User description: "Sign in with Steam. Let a visitor authenticate via Steam OpenID so the app knows who they are... Unauthenticated visitors can see a landing/sign-in page but cannot reach owner-only areas... the signed-in Steam user is the account/owner. No payment or server provisioning in this feature."

## User Scenarios & Testing *(mandatory)*

This feature establishes **identity**: who a person is, proven through Steam. It is the foundation the
server-request flow and server ownership build on — the signed-in Steam user *is* the account and
owner. It deliberately includes **no** server request, **no** payment, and **no** server provisioning.

### User Story 1 - Sign in with Steam (Priority: P1)

As a visitor, I can click "Sign in with Steam", complete Steam's login, and return to the app signed
in as myself, with my Steam persona name and avatar shown in the header.

**Why this priority**: Nothing else in the paid product can happen without knowing who the person is.
This is the minimum that delivers value — an identity the rest of the app can build on.

**Independent Test**: From a signed-out browser, click "Sign in with Steam", complete the Steam
login, and confirm you return to the app recognized as your Steam account with your persona name and
avatar visible.

**Acceptance Scenarios**:

1. **Given** a signed-out visitor on the landing/sign-in page, **When** they choose "Sign in with
   Steam" and complete Steam's login, **Then** they return to the app in a signed-in state.
2. **Given** a user just signed in, **When** any page loads, **Then** the header shows their Steam
   persona name and avatar.
3. **Given** a first-time visitor, **When** they sign in successfully, **Then** an account tied to
   their verified Steam identity is created.
4. **Given** a returning user who has signed in before, **When** they sign in again, **Then** they
   are recognized as the same existing account (not a duplicate).

---

### User Story 2 - Owner-only areas require sign-in (Priority: P2)

As the platform, I ensure that owner-only areas — a user's servers, requesting a server, and the
admin console — are reachable only when signed in; a signed-out visitor is sent to the sign-in page
and, after signing in, continues to the place they were trying to reach.

**Why this priority**: Identity is only useful if it actually gates access. This makes the sign-in
meaningful and protects owner functionality that later features add.

**Independent Test**: While signed out, attempt to open an owner-only area directly; confirm you are
redirected to sign-in, and after completing sign-in you land on the area you originally requested.

**Acceptance Scenarios**:

1. **Given** a signed-out visitor, **When** they try to open an owner-only area, **Then** they are
   redirected to the sign-in page instead.
2. **Given** a signed-out visitor redirected to sign-in from a specific area, **When** they complete
   sign-in, **Then** they are taken to that originally requested area.
3. **Given** a signed-out visitor, **When** they open the landing/sign-in page, **Then** it displays
   without requiring sign-in.
4. **Given** a signed-in user, **When** they open an owner-only area, **Then** it displays normally.

---

### User Story 3 - Stay signed in, and sign out (Priority: P3)

As a signed-in user, my signed-in state persists across page loads and navigation until I sign out or
my session expires; and I can sign out at any time, after which I am treated as a visitor again.

**Why this priority**: Completes the identity lifecycle. Valuable, but the app is already usable for
a single session once US1/US2 exist.

**Independent Test**: Sign in, navigate/reload several pages and confirm you stay signed in; then sign
out and confirm owner-only areas are no longer reachable.

**Acceptance Scenarios**:

1. **Given** a signed-in user, **When** they reload or navigate between pages, **Then** they remain
   signed in without repeating the Steam login.
2. **Given** a signed-in user, **When** they choose "Sign out", **Then** their session ends and the
   header returns to a signed-out state.
3. **Given** a user who has signed out, **When** they try to open an owner-only area, **Then** they
   are redirected to sign-in.
4. **Given** a session that has passed its expiry, **When** the user next makes a request, **Then**
   they are treated as signed out and must sign in again.

---

### Edge Cases

- **User cancels/declines at Steam**: they return unauthenticated with a friendly "sign-in was not
  completed" message and no partial session.
- **Unverifiable or forged return**: if the identity returned cannot be verified as genuinely from
  Steam, no session is created and an error is shown (security-critical — must never sign in).
- **Steam is unavailable**: the sign-in attempt fails gracefully with a "try again later" message;
  the visitor stays unauthenticated.
- **Avatar/persona unavailable**: if the display name or avatar can't be retrieved, the app shows a
  sensible fallback (e.g. a default avatar and the account's identifier) rather than breaking.
- **Deep link while signed out**: opening an owner-only URL directly sends the user through sign-in
  and then on to that URL.
- **Session expiry mid-use**: the next action after expiry cleanly returns the user to sign-in
  without a broken/error page.
- **Persona changed on Steam**: on a later sign-in, the stored persona name/avatar update to Steam's
  current values.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST present a "Sign in with Steam" action on a landing/sign-in page that
  starts Steam's login flow.
- **FR-002**: On return from Steam, the system MUST verify server-side that the identity is genuinely
  from Steam before establishing any signed-in session; unverifiable responses MUST NOT sign the user
  in.
- **FR-003**: On first successful sign-in, the system MUST create an account keyed to the verified
  Steam identity; on subsequent sign-ins it MUST reuse that same account.
- **FR-004**: The system MUST establish a signed-in session bound to the account and keep the user
  signed in across page loads and navigation until sign-out or session expiry.
- **FR-005**: While signed in, the system MUST display the user's Steam persona name and avatar in the
  header on every page, with a fallback if either is unavailable.
- **FR-006**: The system MUST provide a "Sign out" action that ends the session; afterward the user is
  treated as unauthenticated.
- **FR-007**: The system MUST restrict owner-only areas (the user's servers, requesting a server, the
  admin console) to signed-in users, redirecting signed-out visitors to sign-in and then returning
  them to the originally requested area after they sign in.
- **FR-008**: The system MUST allow unauthenticated visitors to view the landing/sign-in page.
- **FR-009**: The system MUST NOT store user passwords; account identity is derived solely from Steam.
- **FR-010**: The system MUST expire sessions after a defined period and treat requests on an expired
  session as signed out.
- **FR-011**: If the user cancels at Steam or Steam is unavailable, the system MUST leave the user
  unauthenticated and show a clear, friendly message (no partial or broken state).
- **FR-012**: On each successful sign-in, the system MUST refresh the stored persona name and avatar to
  Steam's current values.

### Key Entities *(include if feature involves data)*

- **User account**: a person as identified by Steam. Attributes: the verified Steam identity
  (unique), current persona name, avatar reference, first-seen timestamp, last-sign-in timestamp. One
  account per Steam identity. This is also the future **owner** of purchased servers.
- **Session**: an active signed-in association between a browser and a user account, with a creation
  time and an expiry. Ends on sign-out or expiry.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new visitor can go from the sign-in page to a signed-in state by completing Steam's
  login in a single attempt, in under ~30 seconds (excluding time spent on Steam's own screens).
- **SC-002**: 100% of owner-only areas are unreachable while signed out — every attempt redirects to
  sign-in.
- **SC-003**: After signing in, the user's persona name and avatar appear on every page of the app.
- **SC-004**: A signed-in user stays signed in across at least 10 page loads/navigations without being
  asked to log in again (until they sign out or the session expires).
- **SC-005**: Signing out makes all owner-only areas unreachable again with a single action.
- **SC-006**: A returning user who signs in maps to exactly one account — no duplicate accounts are
  created across repeated sign-ins.
- **SC-007**: No forged or unverifiable sign-in response ever results in a signed-in session (0%).

## Assumptions

- **Identity provider**: authentication is via **Steam** only (Steam's OpenID sign-in). No email/
  password, no other social logins this phase — consistent with Constitution v2.0.0 (Principle VIII).
- **Session lifetime**: sessions are persistent ("stay signed in") with a default lifetime of ~30 days,
  after which re-sign-in is required; exact duration is a tunable setting decided in planning. Users
  can end a session early via sign-out.
- **Ownership granularity**: one account = one Steam identity = an individual owner (the captain). No
  multi-member team accounts or roles this phase (out of scope per the constitution).
- **Relationship to feature 001**: the existing app-shell screens that represent "the user's servers"
  and the admin console become owner-only under FR-007; the placeholder/demo data remains until real
  servers exist (later features). The public landing/sign-in page is new.
- **No requests, payments, or provisioning**: requesting a server, payment, and creating servers are
  explicitly *not* part of this feature — the "request a server" area only needs to exist as a gated
  (sign-in-required) destination, not to function yet. (Payment is handled out-of-band by the
  operator; the app never processes payments — see Constitution.)
- **Secrets**: any keys needed to talk to Steam and to sign sessions come from OpenBao and are never
  hardcoded or logged (Principle IV).
- **Audience/environment**: current desktop browsers; the app is served over HTTPS.
