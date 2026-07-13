# Phase 0 Research: Sign in with Steam

All Technical Context items were resolvable from the spec, the constitution, and the existing 001
app. No open `NEEDS CLARIFICATION` markers remain.

## Decision 1 — Steam OpenID verification (server-side)

- **Decision**: Implement Steam's OpenID 2.0 login directly with a small `steam.py` helper using
  `requests`: build the redirect to `https://steamcommunity.com/openid/login`, and on return **verify
  the assertion server-side** by POSTing the returned params back with `openid.mode=check_authentication`
  and requiring `is_valid:true`. Extract the 64-bit SteamID from the validated `claimed_id`.
- **Rationale**: Steam only offers OpenID (no OAuth). The check_authentication round-trip is the
  security-critical step (FR-002, SC-007) — it MUST happen before any session. A ~40-line helper with
  one dependency (`requests`) is the smallest thing that works (Principle I) and avoids stale OpenID
  libraries.
- **Alternatives considered**: `flask-openid` / `python3-openid` (heavier, less maintained, more
  surface); trusting the redirect params without check_authentication (**rejected — insecure**, would
  let a forged return sign a user in, violating Principle IV / SC-007).

## Decision 2 — Session as a signed, expiring cookie

- **Decision**: Use Flask's built-in signed-cookie session. On sign-in store the verified SteamID in
  `session`, set `session.permanent = True`, and set `PERMANENT_SESSION_LIFETIME` to the configured
  lifetime (default 30 days). Sign-out clears the session.
- **Rationale**: Stateless, no session table, satisfies "persists across page loads until sign-out or
  expiry" (FR-004, FR-010) with zero extra infrastructure. The cookie is signed by `SECRET_KEY`
  (from OpenBao), so it cannot be forged. The spec's **Session** entity is realized as this cookie.
- **Alternatives considered**: server-side session store (Redis/DB) — unnecessary at this scale and
  adds infrastructure; rejected for now, revisit if server-side revocation is needed.

## Decision 3 — Persona name + avatar via Steam Web API

- **Decision**: After verifying identity, fetch display data from
  `ISteamUser/GetPlayerSummaries` (Steam Web API) using a **Steam Web API key from OpenBao**, and
  store `persona_name` + `avatar_url` on the user row; refresh them on every sign-in (FR-012). If the
  call fails or fields are missing, fall back to a default avatar and the SteamID (FR-005 edge case).
- **Rationale**: The claimed_id gives only the SteamID; the persona name/avatar require the Web API.
  Refresh-on-login keeps it current without a background job.
- **Alternatives considered**: scraping the profile page (brittle); caching indefinitely (goes stale
  when a user changes their Steam persona).

## Decision 4 — Persistence: SQLite via stdlib

- **Decision**: A single `users` table in SQLite accessed through a thin `db.py` (connection + schema
  init) and `accounts.py` (upsert/fetch). DB path from `DB_PATH` env (local file in dev; a
  PVC-mounted path in the container). Schema initialized idempotently on app startup.
- **Rationale**: First persisted entity; stdlib `sqlite3` is the smallest durable option (Principle I)
  and needs no new dependency. A thin data-access seam leaves room to move to Postgres/an ORM as the
  metadata store grows (requests, servers).
- **Alternatives considered**: SQLAlchemy now (more future-proof but a heavier dep before it's needed);
  in-memory only (rejected — accounts must survive restarts, FR-003/SC-006).

## Decision 5 — Route guard & landing page

- **Decision**: A `@login_required` decorator in `security.py` redirects anonymous users to `/login`
  with the originally requested path captured (e.g. a signed `next` param) and returned to after
  sign-in (FR-007, US2). A `current_user()` helper (backed by the session SteamID + user row) is
  injected into templates for the header. `/` renders the public **landing** page for anonymous
  visitors and the dashboard for signed-in users (FR-008). The 001 owner-only routes
  (servers/console) get the decorator.
- **Rationale**: Standard, minimal Flask pattern; keeps the guard in one place and makes later
  owner-only areas (request-a-server) trivially protectable.
- **Alternatives considered**: `flask-login` (adds a dependency and a user-loader abstraction heavier
  than needed for a single-identity-source app); global before_request guard (harder to exempt public
  routes cleanly).

## Decision 6 — Secrets, base URL, and exposure

- **Decision**: `SECRET_KEY` (session signing) and `STEAM_API_KEY` come from **OpenBao**, surfaced to
  the pod as a Kubernetes Secret (documented by `deploy/secret.example.yaml`, no real values in repo).
  A `BASE_URL` config sets the OpenID **realm/return_to** so Steam redirects the browser back to the
  right place. The app must be **reachable by users over HTTPS** and have **outbound** access to
  `steamcommunity.com` / `api.steampowered.com`.
- **Rationale**: Principle IV (secrets from OpenBao, never hardcoded/logged) and Principle VI
  (everything as code). The realm must match the deployed origin or Steam rejects the return.
- **Alternatives / open items for deployment (not blocking this feature's code)**: how the app is
  exposed publicly (Ingress/LoadBalancer + TLS) is a deployment task; 001's ClusterIP-only Service is
  insufficient for real Steam sign-in and must be revisited before going live. Local dev works via
  `BASE_URL=http://localhost:5000` as long as the dev box has outbound internet.

## Decision 7 — Testing without hitting Steam

- **Decision**: Mock `steam.py`'s verification and Web API calls in tests. Integration tests drive the
  login flow by faking a verified return (patch the verifier to yield a known SteamID), then assert
  session state, header rendering, guard redirect + return-to, logout, and expired-session handling.
- **Rationale**: Deterministic, offline, fast; exercises the app's own logic (the security-critical
  part) rather than Steam's servers.
