"""Server persistence, access control, and the runtime-window lifecycle.

Replaces the hard-coded `SAMPLE_SERVERS` list that `app/models.py` carried through
features 001-004. State here is real and persisted; the compute behind it is
**simulated** this increment (see specs/005-servers-page/spec.md, "Scope of this
increment"). Feature 006 replaces the transitions with real cluster operations behind
this same seam rather than rewriting the page.

Access follows the rule established in feature 004 and reused verbatim: you may see and
join a server if you own it, or if it is bound to an RGL team you are on. An
inaccessible server must be indistinguishable from one that does not exist, so
resolution returns None and routes 404 (never 403).

The administrative (RCON) password is deliberately absent from this module and from the
`servers` table. It belongs in the secret store and must never reach a template.
"""
from datetime import datetime, timedelta, timezone

from flask import current_app

from .db import get_db
from .rgl_store import utc_now

# Lifecycle states. `pending_payment` means the user asked for a server but payment has
# not completed — the scrim stands on its own and must say plainly that no server is
# attached, rather than implying one is coming.
PENDING_PAYMENT = "pending_payment"
SCHEDULED = "scheduled"
STARTING = "starting"
RUNNING = "running"
IN_GRACE = "in_grace"
STOPPED = "stopped"
CANCELLED = "cancelled"
FAILED = "failed"
UNKNOWN = "unknown"

TERMINAL_STATES = (STOPPED, CANCELLED, FAILED)
LIVE_STATES = (RUNNING, IN_GRACE)

# Why a server stopped. Without this a team cannot tell "your time ran out" from
# "something broke", and those call for completely different reactions.
REASON_TIME_EXPIRED = "time_expired"
REASON_CANCELLED = "cancelled"
REASON_FAILED_TO_PLACE = "failed_to_place"

STATE_LABELS = {
    PENDING_PAYMENT: "Awaiting payment",
    SCHEDULED: "Scheduled",
    STARTING: "Starting",
    RUNNING: "Running",
    IN_GRACE: "Overtime",
    STOPPED: "Stopped",
    CANCELLED: "Cancelled",
    FAILED: "Failed to start",
    UNKNOWN: "Unknown",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(stamp: str | None) -> datetime | None:
    if not stamp:
        return None
    when = datetime.fromisoformat(stamp)
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def window_for(scheduled_at: str, credits: int = 1) -> tuple[str, str]:
    """The runtime window a scrim's server is entitled to.

    Starts at the scrim's **scheduled time**, not at whenever provisioning finished:
    the server has to be joinable when the match starts, and the time spent getting it
    ready is not the team's to pay for. A team that turns up late loses its own time.
    """
    start = _parse(scheduled_at)
    minutes = current_app.config["CREDIT_MINUTES"] * credits
    return start.isoformat(timespec="seconds"), (
        start + timedelta(minutes=minutes)).isoformat(timespec="seconds")


# --- reads ---------------------------------------------------------------------------

def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


def get_server(server_id) -> dict | None:
    row = get_db().execute("SELECT * FROM servers WHERE id = ?", (server_id,)).fetchone()
    return dict(row) if row else None


def can_access(server: dict, steam_id: str, team_ids) -> bool:
    """Own it, or be on the team it is bound to. Nothing else — a server spun up for
    another team's scrim is none of your business."""
    if server.get("owner_steam_id") and server["owner_steam_id"] == steam_id:
        return True
    team_id = server.get("team_id")
    return team_id is not None and team_id in set(team_ids or ())


def accessible_servers(steam_id: str, team_ids) -> list[dict]:
    """Servers this viewer may see and join. An empty list is a valid state."""
    ids = list(team_ids or ())
    placeholders = ",".join("?" * len(ids)) if ids else "NULL"
    rows = get_db().execute(
        f"""SELECT * FROM servers
            WHERE owner_steam_id = ? OR team_id IN ({placeholders})
            ORDER BY COALESCE(window_starts_at, created_at) ASC""",
        (steam_id, *ids),
    ).fetchall()
    return _rows_to_dicts(rows)


def get_accessible_server(server_id, steam_id: str, team_ids) -> dict | None:
    """Resolve by id only if this viewer may access it. None means the route should
    404, so an inaccessible server looks exactly like a nonexistent one."""
    server = get_server(server_id)
    if server is None or not can_access(server, steam_id, team_ids):
        return None
    return server


def server_for_scrim(scrim_id) -> dict | None:
    row = get_db().execute(
        "SELECT * FROM servers WHERE scrim_id = ?", (scrim_id,)).fetchone()
    return dict(row) if row else None


def is_owner(server: dict, steam_id: str) -> bool:
    return server.get("owner_steam_id") == steam_id


# --- display helpers ----------------------------------------------------------------

def state_label(server: dict) -> str:
    return STATE_LABELS.get(server.get("state"), "Unknown")


def is_live(server: dict) -> bool:
    return server.get("state") in LIVE_STATES


def slots_display(server: dict) -> str:
    """Player count against capacity. `players` of None means we could not determine
    live state, which is distinct from an empty server and must read that way."""
    players = server.get("players")
    shown = "?" if players is None else players
    return f"{shown}/{server.get('max_slots')}"


def minutes_remaining(server: dict) -> int | None:
    """Whole minutes left in the current window, or None when there is no window.
    Negative while inside the grace period, which is what the template keys on."""
    ends = _parse(server.get("window_ends_at"))
    if ends is None:
        return None
    return int((ends - _now()).total_seconds() // 60)


def grace_minutes_remaining(server: dict) -> int | None:
    """Minutes of unpaid grace left. Only meaningful while `in_grace`."""
    ends = _parse(server.get("window_ends_at"))
    if ends is None or server.get("state") != IN_GRACE:
        return None
    deadline = ends + timedelta(minutes=current_app.config["GRACE_MINUTES"])
    return max(0, int((deadline - _now()).total_seconds() // 60))


def stopped_explanation(server: dict) -> str | None:
    """Why this server is not running, in the viewer's terms. A blank state with no
    explanation is the thing this exists to prevent."""
    state = server.get("state")
    if state == PENDING_PAYMENT:
        return "No server is attached — payment was never completed."
    if state == SCHEDULED:
        return "Not started yet; it will be ready when the scrim begins."
    if state == STARTING:
        return "Starting up now."
    if state == CANCELLED:
        return "Cancelled before it started; the credits were returned."
    if state == FAILED:
        return ("Could not be started, so no credits were charged. "
                "Arrange somewhere else to play.")
    if state == STOPPED:
        if server.get("stopped_reason") == REASON_TIME_EXPIRED:
            return "Stopped because its time ran out."
        return "Stopped."
    if state == UNKNOWN:
        return "Live state could not be determined just now."
    return None


# --- writes -------------------------------------------------------------------------

def create_server(*, owner_steam_id: str, team_id: int | None, name: str,
                  map_name: str, max_slots: int, state: str,
                  scrim_id=None, join_password: str | None = None,
                  address: str | None = None, players: int | None = None,
                  window_starts_at: str | None = None,
                  window_ends_at: str | None = None, demo: bool = False):
    """Insert a server and return its id."""
    now = utc_now()
    cur = get_db().execute(
        """INSERT INTO servers (scrim_id, owner_steam_id, team_id, state, name, map,
                                max_slots, join_password, address, players,
                                window_starts_at, window_ends_at, demo,
                                created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (scrim_id, owner_steam_id, team_id, state, name, map_name, max_slots,
         join_password, address, players, window_starts_at, window_ends_at,
         int(demo), now, now),
    )
    get_db().commit()
    return cur.lastrowid


def set_state(server_id, state: str, *, stopped_reason: str | None = None) -> None:
    get_db().execute(
        """UPDATE servers SET state = ?, stopped_reason = COALESCE(?, stopped_reason),
                              updated_at = ? WHERE id = ?""",
        (state, stopped_reason, utc_now(), server_id),
    )
    get_db().commit()


def update_settings(server_id, *, name: str, map_name: str, max_slots: int,
                    join_password: str | None) -> None:
    """Apply owner-editable settings. `[sim]` — applied to simulated state this
    increment; feature 006 pushes the same change to a real server."""
    get_db().execute(
        """UPDATE servers SET name = ?, map = ?, max_slots = ?, join_password = ?,
                              updated_at = ? WHERE id = ?""",
        (name, map_name, max_slots, join_password, utc_now(), server_id),
    )
    get_db().commit()


def extend_window(server_id, minutes: int) -> str:
    """Push `window_ends_at` out and return the new boundary.

    Extending from the existing boundary rather than from now is what keeps a server
    running continuously — a team that buys time with two minutes to spare does not
    lose those two minutes, and players see no interruption.
    """
    server = get_server(server_id)
    ends = _parse(server.get("window_ends_at")) or _now()
    new_end = (ends + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    get_db().execute(
        "UPDATE servers SET window_ends_at = ?, updated_at = ? WHERE id = ?",
        (new_end, utc_now(), server_id),
    )
    get_db().commit()
    return new_end


def mark_grace_used(server_id) -> None:
    """The grace is once per server, not once per window. Granting it per extension
    would quietly make every credit buy 45 minutes instead of 30."""
    get_db().execute(
        "UPDATE servers SET grace_used = 1, updated_at = ? WHERE id = ?",
        (utc_now(), server_id),
    )
    get_db().commit()


def move_window(scrim_id, scheduled_at: str) -> None:
    """Follow a rescheduled scrim. The window length is preserved, so nothing is
    consumed or returned — only the boundaries move."""
    server = server_for_scrim(scrim_id)
    if server is None or server["state"] in TERMINAL_STATES:
        return
    start, _unused = window_for(scheduled_at)
    old_start = _parse(server.get("window_starts_at"))
    old_end = _parse(server.get("window_ends_at"))
    length = (old_end - old_start) if (old_start and old_end) else timedelta(
        minutes=current_app.config["CREDIT_MINUTES"])
    new_end = (_parse(start) + length).isoformat(timespec="seconds")
    get_db().execute(
        """UPDATE servers SET window_starts_at = ?, window_ends_at = ?, updated_at = ?
           WHERE id = ?""",
        (start, new_end, utc_now(), server["id"]),
    )
    get_db().commit()


def servers_needing_reconcile() -> list[dict]:
    """Every server whose state could still change on the clock."""
    rows = get_db().execute(
        "SELECT * FROM servers WHERE state IN (?,?,?,?)",
        (SCHEDULED, STARTING, RUNNING, IN_GRACE),
    ).fetchall()
    return _rows_to_dicts(rows)
