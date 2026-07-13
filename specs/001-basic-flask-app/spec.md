# Feature Specification: Basic App Shell & Container Build

**Feature Branch**: `001-basic-flask-app`

**Created**: 2026-07-09

**Status**: Draft

**Input**: User description: "Create the basic flask app. so we Can get the Ui components I need then we can start getting it to work. I want to follow the same docker build strategy that we did in the iriga project."

## User Scenarios & Testing *(mandatory)*

This feature delivers the **walking skeleton** of the platform: a hosted web application whose
core screens and interface components are present and navigable (with placeholder data), plus a
reproducible container image that runs on the cluster. It deliberately does **not** yet start real
TF2 servers or talk to the cluster — it establishes the UI surface and the deployment path that
every later feature builds on.

### User Story 1 - See and navigate the app's core screens (Priority: P1)

As the owner, when I open the hosted app I land on a home/dashboard and can navigate to every
primary screen — a list of servers, a "create server" screen, a per-server settings screen, and a
per-server admin console — with each screen rendering its interface components populated by
placeholder/example data.

**Why this priority**: The whole point of this phase is to get the UI components in place so they
can be reviewed and iterated on before any behavior is wired up. Without a navigable shell there is
nothing to evaluate or build onto.

**Independent Test**: Host the app, open it in a browser, and confirm you can reach each primary
screen from the navigation and that each screen displays its components with placeholder content.

**Acceptance Scenarios**:

1. **Given** the app is hosted, **When** the owner opens its address, **Then** a home/dashboard
   screen loads with visible navigation to the other primary screens.
2. **Given** the owner is on the dashboard, **When** they select "servers", **Then** a server-list
   screen renders showing example server rows (name, map, status, player count, address).
3. **Given** the server list is showing, **When** the owner opens a server, **Then** a server-detail
   view renders with its settings and admin-console components visible.
4. **Given** any primary screen is open, **When** the owner uses the navigation, **Then** they can
   return to the dashboard and reach any other primary screen.

---

### User Story 2 - Interact with the settings and admin-console components (Priority: P2)

As the owner, I can open the server-settings form and the admin console and interact with their
controls — typing into the fields (server name, starting map, max slots, join password) and entering
a command in the console — and see the interface respond, even though changes are not yet persisted
or executed against a real server.

**Why this priority**: These are the components the product's value depends on; getting their layout
and interaction feel right early de-risks the later work that wires them to real behavior.

**Independent Test**: Open the settings form and admin console, enter values/commands, and confirm
the controls accept input and the UI gives visible feedback (validation, echoed command, placeholder
response) without errors.

**Acceptance Scenarios**:

1. **Given** the settings screen is open, **When** the owner edits the name, map, slots, and password
   fields, **Then** the form accepts the input and shows basic validation feedback.
2. **Given** the admin console is open, **When** the owner types a command and submits it, **Then**
   the command is echoed into the console output area with a placeholder response.
3. **Given** the server list has no example entries, **When** the list renders, **Then** a clear
   empty-state is shown instead of a broken or blank screen.

---

### User Story 3 - Build and run the app as a container the "iriga way" (Priority: P3)

As the operator, I can build the app into a container image using the same layered build strategy as
the iriga project, push it to the internal registry, and run that image on the cluster so the hosted
app serves the same shell it serves locally.

**Why this priority**: Establishing the deployment path now — matching a known-good pattern — means
every later feature ships the same way; but it can follow once the UI shell exists to package.

**Independent Test**: Run the container build, push the resulting image to the registry, run it, and
confirm the app serves and every primary screen loads from the running container exactly as it does
locally.

**Acceptance Scenarios**:

1. **Given** the project source, **When** the container image is built, **Then** the build reuses a
   cached dependency layer and produces a minimal, non-root runtime image.
2. **Given** a built image, **When** it is pushed to the internal registry and run, **Then** the app
   starts and serves the app shell, and a health check reports the app as ready.
3. **Given** the running container, **When** the owner opens its address, **Then** the same primary
   screens load as in local hosting.

---

### Edge Cases

- **Empty data**: the server list and dashboard render a clear empty-state when there are no example
  servers, never a blank or error page.
- **Unknown route**: navigating to an address that doesn't map to a screen shows a friendly
  not-found page with a way back to the dashboard.
- **Not-yet-wired actions**: buttons/forms for behavior not yet implemented visibly indicate they are
  placeholders rather than silently doing nothing or erroring.
- **Container not ready**: if the app is still starting, the health check reports not-ready so the
  cluster does not route traffic to it prematurely.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST serve a web application that presents a home/dashboard screen at its
  root address.
- **FR-002**: The system MUST provide navigation that lets the owner reach each primary screen —
  dashboard, server list, create-server, server settings, and server admin console — from any screen.
- **FR-003**: The server-list screen MUST display example server entries showing name, current map,
  status (online/offline), player count out of max slots, and public address, and MUST show an
  empty-state when there are none.
- **FR-004**: The server-settings screen MUST present editable form controls for server name,
  starting map, max player slots, and an optional join password, with basic input validation feedback.
- **FR-005**: The admin-console component MUST accept a typed command, echo it into a scrollable
  output area, and display a placeholder response.
- **FR-006**: Interface elements for behavior not yet implemented MUST be visibly marked as
  placeholders rather than appearing fully functional.
- **FR-007**: The system MUST render a friendly not-found page, with a link back to the dashboard,
  for unknown addresses.
- **FR-008**: The application MUST expose a health/readiness signal that reports whether it is ready
  to serve.
- **FR-009**: The application MUST be buildable into a container image using a layered build that
  caches dependencies separately from application code and produces a minimal, non-root runtime image
  (mirroring the iriga project's multi-stage build strategy).
- **FR-010**: The container image MUST be publishable to the internal registry (`harbor.irulast.com`)
  and runnable on the `mke` cluster, serving the same app shell it serves locally.
- **FR-011**: The application's visual presentation MUST be consistent and legible across the primary
  screens (a coherent, "nice" interface), not raw unstyled markup.

### Key Entities *(include if feature involves data)*

- **Server (display model)**: the placeholder representation shown in the UI in this phase — name,
  current map, status, current/maximum player slots, and public address. Not yet persisted or backed
  by a real server; exists to shape the components that later features will bind to real data.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From the hosted app's landing screen, the owner can reach any of the primary screens in
  no more than two navigation steps.
- **SC-002**: 100% of the primary screens (dashboard, server list, create-server, settings, admin
  console) render with placeholder content and no visible errors on first load.
- **SC-003**: The owner can enter values in every settings field and submit a command in the admin
  console and receive visible feedback in under one second, with no page errors.
- **SC-004**: The app can be built into a container image and, when run, becomes ready to serve within
  15 seconds of start, reporting readiness via its health signal.
- **SC-005**: A reviewer unfamiliar with the project can identify each primary screen's purpose from
  its layout alone, without additional explanation.
- **SC-006**: The same image, once pushed to the internal registry and run on the cluster, serves an
  app shell identical to the locally hosted one (all primary screens present).

## Assumptions

- **Technology (owner-directed)**: the web application is implemented with **Flask (Python)**, per
  explicit direction and the project constitution; the container build follows the **iriga project's
  layered multi-stage strategy** — cook/cache dependencies once in a shared stage, then a slim,
  non-root final runtime image, built in a single build session and pushed to `harbor.irulast.com`.
- **Scope of this phase**: no real TF2 server is started, no cluster API calls are made, and no RCON
  traffic occurs yet; all data shown is placeholder. Those behaviors are later features.
- **Authentication**: sign-in is out of scope for this scaffold; the app is reached directly (guarded
  only by the internal/WireGuard network) and real auth arrives in a later feature.
- **Persistence**: no database or durable storage is required in this phase; settings changes need not
  survive a reload.
- **Audience & environment**: a single trusted owner using a current desktop browser; the app is
  hosted internally on the `mke` cluster and reached over the internal network.
- **Dependency**: publishing the image assumes access to `harbor.irulast.com` and a running `mke`
  cluster (WireGuard tunnel up), consistent with the project's target environment.
