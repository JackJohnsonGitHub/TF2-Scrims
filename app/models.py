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
    # Who may see and join this server (constitution v3.0.0, Principle VIII): the
    # captain who was granted it, and the RGL team it is bound to. A server rented
    # or auto-started for another team's scrim is none of your business.
    owner_steam_id: str | None = None
    team_id: int | None = None

    @property
    def slots_display(self) -> str:
        return f"{self.players}/{self.max_slots}"

    @property
    def status_label(self) -> str:
        return "Online" if self.status == "online" else "Offline"

    @property
    def is_online(self) -> bool:
        return self.status == "online"


# The placeholder servers belong to the demo rival team — the same identity
# scripts/seed_demo_team.py seeds — so they exercise the access rule honestly:
# they are somebody else's servers unless you are on that team.
DEMO_OWNER_STEAM_ID = "90000000000000001"
DEMO_TEAM_ID = 9990001

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
        owner_steam_id=DEMO_OWNER_STEAM_ID,
        team_id=DEMO_TEAM_ID,
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
        owner_steam_id=DEMO_OWNER_STEAM_ID,
        team_id=DEMO_TEAM_ID,
    ),
]


def all_servers() -> list[Server]:
    """Every server the platform knows about, ignoring who may see it. Callers
    rendering anything user-facing want `accessible_servers` instead."""
    return list(SAMPLE_SERVERS)


def can_access(server: Server, steam_id: str, team_ids) -> bool:
    """You may see and join a server if you own it, or if it is bound to an RGL
    team you are on. Everything else — including servers spun up for another
    team's scrim — stays hidden."""
    if server.owner_steam_id and server.owner_steam_id == steam_id:
        return True
    return server.team_id is not None and server.team_id in set(team_ids or ())


def accessible_servers(steam_id: str, team_ids) -> list[Server]:
    """The servers this viewer may see and join (empty list is a valid state)."""
    return [s for s in SAMPLE_SERVERS if can_access(s, steam_id, team_ids)]


def get_server(server_id: str) -> Server | None:
    return next((s for s in SAMPLE_SERVERS if s.id == server_id), None)


def get_accessible_server(server_id: str, steam_id: str, team_ids) -> Server | None:
    """Resolve a server by id only if this viewer may access it — None means the
    route should 404, so an inaccessible server is indistinguishable from one that
    does not exist."""
    server = get_server(server_id)
    if server is None or not can_access(server, steam_id, team_ids):
        return None
    return server


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
