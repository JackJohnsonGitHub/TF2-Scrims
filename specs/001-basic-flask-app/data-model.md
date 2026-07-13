# Phase 1 Data Model: Basic App Shell & Container Build

This phase has **no persistent data**. The only model is an in-process **display view model** used to
populate the UI components with placeholder content. It exists to shape the components that later
features will bind to real, cluster-backed data.

## Entity: Server (display view model)

Represents one TF2 server as shown in the UI. In this phase, instances are hard-coded sample data in
`app/models.py`; nothing is stored or provisioned.

| Field | Type | Description | Example |
|---|---|---|---|
| `id` | string (slug) | Stable identifier used in URLs (`/servers/<id>`). | `"friday-pug"` |
| `name` | string | Owner-facing hostname / display name. | `"Friday Night PUG"` |
| `map` | string | Current / starting map. | `"cp_process_final"` |
| `status` | enum: `online` \| `offline` | Placeholder run state. | `online` |
| `players` | integer ≥ 0 | Current connected player count (placeholder). | `12` |
| `max_slots` | integer 1–32 | Maximum player slots. | `24` |
| `address` | string \| null | Public `IP:port` to share; `null` when offline/unassigned. | `"10.0.0.5:27015"` |

### Validation rules (UI-level, for the settings form — FR-004)

- `name`: required, non-empty, trimmed; reasonable max length (e.g. ≤ 64 chars).
- `map`: required, non-empty; free text this phase (no map-existence check yet).
- `max_slots`: required integer within 1–32 (TF2's practical range).
- `join_password` (form-only field, not stored this phase): optional; if present, non-empty.

> These are **presentation validations** to give the form feedback (FR-004). No values are persisted;
> submitting the form does not change any real server this phase.

### Derived / display helpers

- `slots_display` → `"{players}/{max_slots}"` (e.g. `"12/24"`).
- `status_label` → human label + style class driven by `status`.
- Empty-state: when the sample collection is empty, the server-list screen renders an empty-state
  message instead of rows (FR-003, edge case).

## Relationships

None. A flat collection of `Server` view models is all the UI needs this phase.

## State transitions

None modeled yet. Real lifecycle (create → starting → online → stopped → deleted) belongs to the
later provisioning feature; the placeholder `status` field is static per sample instance.
