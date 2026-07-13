# Phase 1 Contract: Auth & Guard Routes

New/changed HTTP routes for Steam sign-in and access control. Server-rendered; no JSON API.

## Auth routes (new)

| Method | Path | Purpose | Maps to |
|---|---|---|---|
| GET | `/login` | Redirect the browser to Steam's OpenID login (realm/return_to from `BASE_URL`). Accepts an optional signed `next` to return to after sign-in. | FR-001, FR-007 |
| GET | `/login/return` | Steam redirects here. **Verify the assertion server-side** (check_authentication); on success upsert the user, establish the session, then redirect to `next` or the dashboard. On failure render the login-error page. | FR-002, FR-003, FR-004, FR-011, FR-012 |
| GET, POST | `/logout` | Clear the session; redirect to the landing page. | FR-006 |

## Screen/route changes (existing)

| Method | Path | Change | Maps to |
|---|---|---|---|
| GET | `/` | Anonymous → render **landing** (public sign-in). Signed in → render dashboard. | FR-008 |
| GET | `/servers`, `/servers/new`, `/servers/<id>` | Now `@login_required` — anonymous is redirected to `/login?next=…`. | FR-007 |
| POST | `/servers/new`, `/servers/<id>/settings`, `/servers/<id>/console` | Now `@login_required`. | FR-007 |
| GET | `/healthz` | Unchanged — stays public (readiness probe must not require auth). | (001 FR-008) |

## Behavior contract

- **Verification is mandatory (FR-002 / SC-007)**: `/login/return` MUST complete the server-side
  check_authentication and get `is_valid:true` before any session is set. A forged/unverifiable
  return MUST render the login-error page and set **no** session.
- **Account upsert (FR-003 / SC-006)**: first successful sign-in creates the user row; subsequent
  sign-ins reuse it and refresh persona/avatar/last_login (FR-012).
- **Session persistence (FR-004 / FR-010 / SC-004)**: the signed session persists across requests
  until sign-out or expiry; a request with an expired/absent session is treated as anonymous.
- **Guard + return-to (FR-007 / US2)**: an anonymous request to an owner-only route redirects to
  `/login?next=<original>`; after sign-in the user lands on `<original>`. The `next` target MUST be a
  local path (reject open redirects to external hosts).
- **Header identity (FR-005)**: signed-in responses show persona name + avatar (or default avatar
  fallback) and a Sign-out control; anonymous responses show a Sign-in control.
- **Failure handling (FR-011)**: user-cancelled at Steam, Steam unavailable, or verification failure
  → friendly `login_error.html`, user stays anonymous, no partial session.

## Response expectations (for tests)

- `/login` → 302 to `steamcommunity.com/openid/login` (assert redirect host + realm/return params).
- `/login/return` with a (mocked) valid assertion → 302 to dashboard or `next`; session cookie set;
  a `users` row exists.
- `/login/return` with an invalid/mocked-failed assertion → 200 rendering `login_error.html`; no
  session.
- Anonymous GET `/servers` → 302 to `/login?next=/servers`.
- After sign-in, GET `/servers` → 200 with the header showing the persona name.
- `/logout` → 302 to `/`; subsequent GET `/servers` → 302 to `/login`.
- Anonymous GET `/` → 200 rendering the landing page; GET `/healthz` → 200 (still public).

> Out of scope (documented so tests don't expect it): server requests, payment, provisioning, team
> accounts/roles. Owner-only areas need only exist and be guarded, not function.
