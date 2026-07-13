# Phase 1 Data Model: Sign in with Steam

Introduces the app's first persisted entity. The **User account** is stored in SQLite; the
**Session** is not a table — it is realized as a signed, expiring cookie (see research Decision 2).

## Entity: User account (persisted — `users` table)

One row per verified Steam identity. Created on first sign-in, reused thereafter (FR-003, SC-006).

| Field | Type | Description | Notes |
|---|---|---|---|
| `steam_id` | TEXT, PRIMARY KEY | 64-bit SteamID as a string | The verified identity; unique. Also the future server **owner** key. |
| `persona_name` | TEXT | Steam display name | Refreshed on every sign-in (FR-012); fallback if unavailable. |
| `avatar_url` | TEXT, nullable | URL of the Steam avatar | Nullable → header shows a default avatar (FR-005). |
| `created_at` | TEXT (ISO-8601) | First-seen timestamp | Set once, on account creation. |
| `last_login_at` | TEXT (ISO-8601) | Most recent successful sign-in | Updated every sign-in. |

### Rules
- **Upsert on sign-in**: if `steam_id` exists → update `persona_name`, `avatar_url`, `last_login_at`;
  else insert with `created_at = last_login_at = now` (SC-006: never a duplicate account).
- `steam_id` is only ever written from a **server-side verified** OpenID assertion (FR-002) — never
  from client-supplied input.
- No passwords or credential material are stored (FR-009).

## Realized (not persisted): Session

An active sign-in association between a browser and a `User account`.

- **Representation**: Flask signed-cookie session containing the verified `steam_id`, marked
  `permanent`, expiring after `PERMANENT_SESSION_LIFETIME` (default 30 days).
- **Created**: on successful sign-in. **Ended**: on sign-out (session cleared) or expiry.
- **Integrity**: signed with `SECRET_KEY` (from OpenBao); an unsigned/tampered cookie is rejected and
  treated as anonymous.
- **State**: anonymous (no valid session) ↔ signed-in (valid, unexpired session resolving to a user
  row). Expired/absent → anonymous (FR-010).

## Derived / helpers
- `current_user()` → resolves the session's `steam_id` to its `users` row, or `None` when anonymous;
  drives the header (persona name + avatar or fallback) and the `@login_required` guard.
