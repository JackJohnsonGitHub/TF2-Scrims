"""Display view models for the app shell.

This phase has NO persistence and provisions NO real servers. `Server` is a
placeholder representation used to shape the UI components that later features
will bind to real, cluster-backed data. See specs/001-basic-flask-app/data-model.md.
"""
from dataclasses import dataclass

# Presentation-level bounds (TF2's practical range). Used by the settings form.
NAME_MAX_LEN = 64
SLOTS_MIN = 1
SLOTS_MAX = 32


@dataclass
class Server:
    """A TF2 server as shown in the UI (placeholder — not persisted)."""

    id: str
    name: str
    map: str
    status: str  # "online" | "offline"
    players: int
    max_slots: int
    address: str | None
    demo: bool = False  # placeholder sample data, not a real server

    @property
    def slots_display(self) -> str:
        return f"{self.players}/{self.max_slots}"

    @property
    def status_label(self) -> str:
        return "Online" if self.status == "online" else "Offline"

    @property
    def is_online(self) -> bool:
        return self.status == "online"


# Hard-coded sample data so every screen has something to render this phase.
SAMPLE_SERVERS: list[Server] = [
    Server(
        id="friday-pug",
        name="Friday Night PUG",
        map="cp_process_final",
        status="online",
        players=12,
        max_slots=24,
        address="10.0.0.5:27015",
        demo=True,
    ),
    Server(
        id="jump-practice",
        name="Jump Practice",
        map="jump_academy_b4",
        status="offline",
        players=0,
        max_slots=8,
        address=None,
        demo=True,
    ),
]


def all_servers() -> list[Server]:
    """Return the placeholder server collection (empty list is a valid state)."""
    return list(SAMPLE_SERVERS)


def get_server(server_id: str) -> Server | None:
    return next((s for s in SAMPLE_SERVERS if s.id == server_id), None)


def validate_server_settings(name: str, map_name: str, max_slots: str,
                             join_password: str) -> dict[str, str]:
    """Presentation-level validation for the settings/create forms (FR-004).

    Returns a dict of {field: error message}. Empty dict means valid. Nothing is
    persisted this phase — this only drives form feedback.
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
