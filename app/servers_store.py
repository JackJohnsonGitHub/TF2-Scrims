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


def scrim_sides(scrim_id) -> tuple:
    """The two team ids a scrim is between."""
    if not scrim_id:
        return ()
    row = get_db().execute(
        "SELECT proposer_team_id, opponent_team_id FROM scrims WHERE id = ?",
        (scrim_id,),
    ).fetchone()
    if row is None:
        return ()
    return tuple(t for t in (row["proposer_team_id"], row["opponent_team_id"]) if t)


def can_access(server: dict, steam_id: str, team_ids) -> bool:
    """Who may **see and join** a server.

    Both sides of a scrim, not just the side that paid. A match has two teams and they
    both have to get onto the server — if the team that claimed a listing could not see
    the address, the server would be useless to half the people playing on it.

    Control is a separate and narrower question; see `can_manage`.
    """
    if server.get("owner_steam_id") and server["owner_steam_id"] == steam_id:
        return True
    teams = set(team_ids or ())
    if server.get("team_id") is not None and server["team_id"] in teams:
        return True
    return bool(teams & set(scrim_sides(server.get("scrim_id"))))


def accessible_servers(steam_id: str, team_ids) -> list[dict]:
    """Servers this viewer may see and join. An empty list is a valid state."""
    ids = list(team_ids or ())
    placeholders = ",".join("?" * len(ids)) if ids else "NULL"
    rows = get_db().execute(
        f"""SELECT DISTINCT v.* FROM servers v
            LEFT JOIN scrims s ON s.id = v.scrim_id
            WHERE v.owner_steam_id = ?
               OR v.team_id IN ({placeholders})
               OR s.proposer_team_id IN ({placeholders})
               OR s.opponent_team_id IN ({placeholders})
            ORDER BY COALESCE(v.window_starts_at, v.created_at) ASC""",
        (steam_id, *ids, *ids, *ids),
    ).fetchall()
    return _rows_to_dicts(rows)


def team_leaders(team_id) -> set:
    """SteamIDs RGL marks as leaders of a team.

    Authority comes from RGL's own roster data, not an in-app role hierarchy — which is
    both what the constitution's non-goals require and the only source that stays true
    as a team's leadership changes.
    """
    if not team_id:
        return set()
    rows = get_db().execute(
        "SELECT steam_id FROM rgl_rosters WHERE rgl_team_id = ? AND is_leader = 1",
        (team_id,),
    ).fetchall()
    return {r["steam_id"] for r in rows}


def managing_team_for(server: dict) -> int | None:
    """The team whose leaders control this server: the one that proposed the scrim or
    posted the listing. For a season-term server there is no scrim, so it falls back to
    the team the server is bound to."""
    scrim_id = server.get("scrim_id")
    if not scrim_id:
        return server.get("team_id")
    row = get_db().execute(
        "SELECT proposer_team_id FROM scrims WHERE id = ?", (scrim_id,)).fetchone()
    return row["proposer_team_id"] if row else server.get("team_id")


def can_manage(server: dict, steam_id: str) -> bool:
    """Who may **change settings, run commands, and buy more time**.

    Only leaders of the team that proposed the scrim or posted the listing. Deliberately
    narrower than `can_access`: everyone playing needs the address, but a server's
    configuration is the organising team's to set.

    Note this can differ from who paid. If the claiming team bought the server, control
    still sits with the proposing team's leaders — that is the rule as specified.

    **Fallback**: when the proposing team's roster has not been cached (RGL unreachable,
    or a team we have never fetched), no leader is known. Rather than leave a server that
    nobody can control, the owner keeps control until a roster arrives.
    """
    leaders = team_leaders(managing_team_for(server))
    if not leaders:
        return bool(server.get("owner_steam_id")
                    and server["owner_steam_id"] == steam_id)
    return steam_id in leaders


def get_accessible_server(server_id, steam_id: str, team_ids) -> dict | None:
    """Resolve by id only if this viewer may access it. None means the route should
    404, so an inaccessible server looks exactly like a nonexistent one."""
    server = get_server(server_id)
    if server is None or not can_access(server, steam_id, team_ids):
        return None
    return server


def scrims_without_servers(steam_id: str) -> list[dict]:
    """The viewer's upcoming scrims that have no server attached (FR-016).

    This is what lets the Servers page answer "which of my matches still need somewhere
    to play" without navigating anywhere else (SC-001). Covers every side of a scrim the
    viewer is on, and every status that can still be played.
    """
    rows = get_db().execute(
        """SELECT s.id, s.format, s.scheduled_at, s.status,
                  pt.name AS proposer_name, ot.name AS opponent_name
           FROM scrims s
           JOIN rgl_memberships m
                ON m.steam_id = ?
                AND m.rgl_team_id IN (s.proposer_team_id, s.opponent_team_id)
           LEFT JOIN rgl_teams pt ON pt.rgl_team_id = s.proposer_team_id
           LEFT JOIN rgl_teams ot ON ot.rgl_team_id = s.opponent_team_id
           LEFT JOIN servers v ON v.scrim_id = s.id
           WHERE v.id IS NULL
             AND s.status IN ('confirmed', 'open', 'pending')
             AND s.scheduled_at > ?
           ORDER BY s.scheduled_at ASC""",
        (steam_id, utc_now()),
    ).fetchall()
    return [dict(r) for r in rows]


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


def connect_command(server: dict) -> str | None:
    """The line a player pastes into the TF2 console to join.

    Both halves in one string on purpose: an address and a password shown separately is
    two things to copy correctly with twelve people waiting. Returns None when there is
    nothing to join, so no screen offers a command that cannot work.
    """
    if not is_live(server) or not server.get("address"):
        return None
    command = f"connect {server['address']}"
    if server.get("join_password"):
        # Quoted so a password containing a space or semicolon still parses.
        command += f'; password "{server["join_password"]}"'
    return command


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


def is_per_scrim(server: dict) -> bool:
    """A short-lived match server, as opposed to a season-long rental. Decides which
    settings are worth offering: renaming or resizing a server that exists for one
    hour of one match is noise (FR-028)."""
    return server.get("scrim_id") is not None


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


# NOTE: there is deliberately no `move_window` here. FR-082 (a rescheduled scrim's server
# follows it) is deferred: the app has no reschedule flow, so any implementation would be
# unreachable and unverified. It is also only the easy half of the problem — whoever builds
# rescheduling has to decide whether a moved scrim re-reserves, and what happens when its
# server has already run — and a guess at that, sitting here untested, would mislead rather
# than help. See specs/005-servers-page/spec.md FR-082.


def owning_team_for(actor_steam_id: str, scrim: dict) -> int | None:
    """Whichever side of this scrim the actor is actually on.

    Not simply `proposer_team_id`: when someone claims an open listing it is the
    *claimer* who pays, so binding the server to the poster's team would hand
    visibility to the wrong side and hide it from the people who bought it.
    """
    from .rgl_store import is_member
    for candidate in (scrim.get("proposer_team_id"), scrim.get("opponent_team_id")):
        if candidate and is_member(actor_steam_id, candidate):
            return candidate
    return None


def attach_to_scrim(actor_steam_id: str, scrim: dict, team_id: int | None = None) -> int:
    """Reserve a credit and create a scheduled server for this scrim.

    Raises `credits.InsufficientCredits` if the balance cannot cover it. Callers MUST
    have created the scrim already and MUST NOT undo it on failure: a scheduled scrim
    with no server is a valid, honest state, and scheduling is free (Principle I).
    """
    from . import credits

    starts, ends = window_for(scrim["scheduled_at"])
    label = scrim.get("proposer_name") or f"Scrim {scrim['id']}"
    server_id = create_server(
        owner_steam_id=actor_steam_id,
        team_id=team_id or owning_team_for(actor_steam_id, scrim),
        scrim_id=scrim["id"],
        name=f"{label} — {scrim['scheduled_at'][:10]}",
        map_name="cp_process_final",
        max_slots=24,
        state=SCHEDULED,
        window_starts_at=starts,
        window_ends_at=ends,
    )
    try:
        credits.reserve(actor_steam_id, f"Server for scrim {scrim['id']}",
                        scrim_id=scrim["id"], server_id=server_id)
    except Exception:
        # No credit was taken, so leave no half-attached server behind either.
        get_db().execute("DELETE FROM servers WHERE id = ?", (server_id,))
        get_db().commit()
        raise
    return server_id


def release_if_unstarted(scrim_id) -> str | None:
    """Give back a scrim's reserved credit if its server never ran.

    Called when a scrim is cancelled, declined or withdrawn, and when a listing is
    pulled. A team is never charged for a server it did not get (FR-067).
    """
    from . import credits

    server = server_for_scrim(scrim_id)
    if server is None or server["state"] not in (PENDING_PAYMENT, SCHEDULED, STARTING):
        return None
    set_state(server["id"], CANCELLED, stopped_reason=REASON_CANCELLED)
    if server["state"] != PENDING_PAYMENT:
        # PENDING_PAYMENT never reserved anything, so there is nothing to give back.
        credits.release(server["owner_steam_id"], f"Scrim {scrim_id} called off",
                        scrim_id=scrim_id, server_id=server["id"])
        return "released"
    return "cancelled"


def mark_failed_to_place(server_id) -> None:
    """A server the platform could not create. Returns its credit — a visible failure
    beats a silently missing server, and beats charging for one (Principle VII)."""
    from . import credits

    server = get_server(server_id)
    if server is None or server["state"] in TERMINAL_STATES:
        return
    set_state(server_id, FAILED, stopped_reason=REASON_FAILED_TO_PLACE)
    credits.release(server["owner_steam_id"],
                    f"Server {server_id} could not be started",
                    scrim_id=server.get("scrim_id"), server_id=server_id)


def servers_needing_reconcile() -> list[dict]:
    """Every server whose state could still change on the clock."""
    rows = get_db().execute(
        "SELECT * FROM servers WHERE state IN (?,?,?,?)",
        (SCHEDULED, STARTING, RUNNING, IN_GRACE),
    ).fetchall()
    return _rows_to_dicts(rows)
