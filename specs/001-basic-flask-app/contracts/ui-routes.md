# Phase 1 Contract: UI Routes

The app exposes a set of HTTP routes rendering the primary screens plus a readiness endpoint. This is
the interface contract for this web application; screens render server-side HTML. All data is
placeholder this phase (no cluster calls, no persistence).

## Screen routes

| Method | Path | Screen | Renders | Maps to FR |
|---|---|---|---|---|
| GET | `/` | Dashboard | Home with nav to all primary screens; summary of example servers. | FR-001, FR-002 |
| GET | `/servers` | Server list | Table of example `Server` rows (name, map, status, `players/max_slots`, address); empty-state when none. | FR-002, FR-003 |
| GET | `/servers/new` | Create server | Form with fields: name, starting map, max slots, join password. Placeholder submit. | FR-002, FR-004, FR-006 |
| POST | `/servers/new` | Create server (submit) | Validates inputs (presentation only); re-renders with feedback; does **not** create anything. | FR-004, FR-006 |
| GET | `/servers/<id>` | Server detail | Settings form (prefilled) + admin console for that server. | FR-002, FR-004 |
| POST | `/servers/<id>/settings` | Settings submit | Validates + shows feedback; not persisted. | FR-004, FR-006 |
| POST | `/servers/<id>/console` | Admin console command | Echoes the submitted command into the output area with a placeholder response. | FR-005 |
| GET | `/servers/<unknown>` | (not found) | Friendly 404 page with link to dashboard. | FR-007 |
| GET | `/healthz` | (no screen) | `200` + minimal body when ready. | FR-008 |

## Behavior contract

- **Navigation (FR-002)**: `base.html` provides a persistent nav reaching Dashboard and Server list
  from every screen; server-detail and create-server are reachable in ≤ 2 steps from `/` (SC-001).
- **Empty-state (FR-003)**: `/servers` with an empty sample collection renders a labeled empty-state,
  never a blank/error page.
- **Placeholder actions (FR-006)**: create/settings/console submit handlers visibly indicate the
  action is a placeholder (e.g. a flash message: "not wired up yet") rather than silently no-op'ing.
- **Console echo (FR-005)**: POST `/servers/<id>/console` returns the detail screen with the typed
  command appended to a scrollable output region plus a canned placeholder response line.
- **Not found (FR-007)**: unknown paths (including unknown server ids) return HTTP 404 rendering
  `404.html` with a dashboard link.
- **Readiness (FR-008 / SC-004)**: `/healthz` returns `200` once the app factory has initialized; used
  as the k8s readiness probe so traffic isn't routed to a starting pod.

## Response expectations (for integration tests)

- Each GET screen route returns HTTP `200` and includes an identifying marker in the HTML (e.g. a
  screen title or a `data-screen="dashboard"` attribute) so `tests/integration/test_routes.py` can
  assert the right screen rendered.
- `/healthz` returns `200` with a small stable body (e.g. `ok`).
- An unknown path returns HTTP `404` and includes the dashboard link.

> Out of scope this phase (documented so reviewers don't expect it): JSON APIs, authentication,
> real RCON output, real server creation, and persistence. These arrive in later features.
