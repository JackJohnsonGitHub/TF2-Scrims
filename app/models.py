"""Presentation-level validation for the server settings form.

Servers themselves are persisted and resolved by `app/servers_store.py` as of feature
005 — the hard-coded `SAMPLE_SERVERS` list and the `Server` view model that lived here
through features 001-004 are gone. Demo servers are now seeded rows like any other,
which is what lets them exercise the access rule honestly.

Display formatting (slot counts, state labels, why-it-is-not-running) also lives in
`servers_store`, deliberately in one place: a second formatting path here would be a
second truth to keep in step.
"""

# Presentation-level bounds (TF2's practical range). Used by the settings form.
NAME_MAX_LEN = 64
SLOTS_MIN = 1
SLOTS_MAX = 32

# The demo rival identity that `scripts/seed_demo_team.py` seeds. Demo servers belong
# to this team, so they are somebody else's servers unless you are on it — the access
# rule gets exercised by the sample data rather than around it.
DEMO_OWNER_STEAM_ID = "90000000000000001"
DEMO_TEAM_ID = 9990001


def validate_server_settings(name: str, map_name: str, max_slots: str,
                             join_password: str) -> dict[str, str]:
    """Validate the settings form.

    Returns a dict of {field: error message}. Empty dict means valid. Field-scoped so
    a route can reject precisely and apply nothing (FR-024).
    """
    errors: dict[str, str] = {}

    if not name or not name.strip():
        errors["name"] = "Server name is required."
    elif len(name.strip()) > NAME_MAX_LEN:
        errors["name"] = f"Server name must be {NAME_MAX_LEN} characters or fewer."

    if not map_name or not map_name.strip():
        errors["map"] = "Starting map is required."

    try:
        slots = int(max_slots)
        if slots < SLOTS_MIN or slots > SLOTS_MAX:
            errors["max_slots"] = f"Max slots must be between {SLOTS_MIN} and {SLOTS_MAX}."
    except (TypeError, ValueError):
        errors["max_slots"] = "Max slots must be a whole number."

    # join_password is optional; if provided it must be non-empty (not just spaces).
    if join_password is not None and join_password != "" and not join_password.strip():
        errors["join_password"] = "Join password cannot be only whitespace."

    return errors
