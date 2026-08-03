"""Attendance tracking for a team's own scrim listing (feature 004, US3).

Kept separate from the scrim state machine because its rules are orthogonal:
listing-origin scrims only, posting-team members only, self-or-creator writes
(clarification #4), frozen once the scheduled time passes (FR-017). Rows are keyed
by the player's SteamID64 — the same identity space RGL rosters and app accounts
share — with a name snapshot so departed players stay renderable (data-model.md).
"""

from .db import get_db
from .rgl_store import get_roster, is_member, utc_now
from .scrims import ScrimError, ScrimForbidden, get_scrim

FORMAT_SIZES = {"sixes": 6, "prolander": 7, "highlander": 9}
STATUSES = ("attending", "not_attending", "unconfirmed")

STATUS_LABELS = {"attending": "Attending", "not_attending": "Not attending",
                 "unconfirmed": "Unconfirmed"}


def required_players(format_: str) -> int:
    return FORMAT_SIZES.get(format_, 0)


def is_locked(scrim: dict) -> bool:
    """Read-only once the scheduled time has passed or the scrim is dead."""
    return (scrim["scheduled_at"] <= utc_now()
            or scrim["status"] in ("cancelled", "declined"))


def set_status(actor: str, scrim_id: int, player_steam_id: str, status: str,
               player_name: str | None = None) -> None:
    """Upsert one player's attendance. Members mark themselves; the listing's
    creator marks anyone (incl. account-less and departed players); nobody else
    writes (FR-014)."""
    if status not in STATUSES:
        raise ScrimError("Invalid attendance status.")
    scrim = get_scrim(scrim_id)
    if scrim is None:
        raise ScrimError("Scrim not found.", status=404)
    if scrim["origin"] != "listing":
        raise ScrimError("Attendance is tracked on listings only.")
    if scrim["status"] in ("cancelled", "declined"):
        raise ScrimError("This scrim is no longer active.")
    if scrim["scheduled_at"] <= utc_now():
        raise ScrimError("Scrim time has passed — attendance is read-only.")
    if not is_member(actor, scrim["proposer_team_id"]):
        raise ScrimForbidden()
    if actor != scrim["created_by"] and player_steam_id != actor:
        raise ScrimForbidden()

    if not player_name:
        player_name = _resolve_name(scrim, player_steam_id)
    db = get_db()
    db.execute(
        """INSERT INTO scrim_attendance (scrim_id, player_steam_id, player_name,
                                         status, marked_by, updated_at)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT(scrim_id, player_steam_id) DO UPDATE SET
               status = excluded.status, marked_by = excluded.marked_by,
               updated_at = excluded.updated_at""",
        (scrim_id, player_steam_id, player_name, status, actor, utc_now()),
    )
    db.commit()


def _resolve_name(scrim: dict, player_steam_id: str) -> str:
    """Snapshot name: current roster first, then a prior attendance row (departed
    player being re-marked), else the raw id."""
    for p in get_roster(scrim["proposer_team_id"]):
        if p["steam_id"] == player_steam_id:
            return p["name"]
    row = get_db().execute(
        """SELECT player_name FROM scrim_attendance
           WHERE scrim_id = %s AND player_steam_id = %s""",
        (scrim["id"], player_steam_id)).fetchone()
    return row["player_name"] if row else player_steam_id


def roster_with_attendance(scrim: dict) -> list[dict]:
    """The posting team's current roster merged with attendance marks, plus rows
    for marked players who have since left the team (flagged `departed`)."""
    marks = {
        r["player_steam_id"]: r
        for r in get_db().execute(
            "SELECT * FROM scrim_attendance WHERE scrim_id = %s", (scrim["id"],))
    }
    entries = []
    for p in get_roster(scrim["proposer_team_id"]):
        mark = marks.pop(p["steam_id"], None)
        entries.append({
            "steam_id": p["steam_id"], "name": p["name"],
            "is_leader": bool(p["is_leader"]),
            "status": mark["status"] if mark else "unconfirmed",
            "departed": False,
        })
    for steam_id, mark in marks.items():  # marked, but no longer on the roster
        entries.append({
            "steam_id": steam_id, "name": mark["player_name"], "is_leader": False,
            "status": mark["status"], "departed": True,
        })
    return entries


def attending_count(entries: list[dict]) -> int:
    return sum(1 for e in entries if e["status"] == "attending")