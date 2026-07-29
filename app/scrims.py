"""Scrim data access + state machine (both scheduling paths).

Directed proposal:  pending → confirmed (accept) | declined (decline) | cancelled (withdraw)
Open listing:       open → confirmed (claim, atomic first-wins) | cancelled (owner cancel)
Either participant may cancel a confirmed scrim → cancelled (kept, never deleted — FR-015).

Every transition re-checks team membership server-side (FR-016) and none of them
touches servers or payment (FR-018). Times are ISO-8601 UTC throughout.
"""
import sqlite3
from datetime import datetime, timezone

from .db import get_db
from .rgl_store import get_team, is_member, utc_now


class ScrimError(ValueError):
    """A rejected scrim action; `status` is the HTTP status routes should use."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ScrimForbidden(ScrimError):
    """Acting for a team you're not on, or for the wrong side (FR-016)."""

    def __init__(self, message: str = "You are not on that team."):
        super().__init__(message, status=403)


def _require_member(actor: str, team_id: int) -> None:
    if not is_member(actor, team_id):
        raise ScrimForbidden()


def _require_future(scheduled_at: str) -> str:
    try:
        when = datetime.fromisoformat(scheduled_at)
    except (TypeError, ValueError):
        raise ScrimError("Invalid date/time.")
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    if when <= datetime.now(timezone.utc):
        raise ScrimError("The scrim time must be in the future.")
    return when.isoformat(timespec="seconds")


def _insert(format_: str, scheduled_at: str, origin: str, proposer_team_id: int,
            opponent_team_id: int | None, status: str, created_by: str,
            notes: str | None) -> int:
    now = utc_now()
    cur = get_db().execute(
        """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                               opponent_team_id, status, created_by, created_at,
                               updated_at, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (format_, scheduled_at, origin, proposer_team_id, opponent_team_id,
         status, created_by, now, now, notes),
    )
    get_db().commit()
    return cur.lastrowid


def _set_status(scrim_id: int, status: str, opponent_team_id: int | None = None) -> int:
    """Unconditional status write (guards already ran). Returns rows changed."""
    db = get_db()
    if opponent_team_id is None:
        cur = db.execute("UPDATE scrims SET status = ?, updated_at = ? WHERE id = ?",
                         (status, utc_now(), scrim_id))
    else:
        cur = db.execute(
            "UPDATE scrims SET status = ?, opponent_team_id = ?, updated_at = ? WHERE id = ?",
            (status, opponent_team_id, utc_now(), scrim_id))
    db.commit()
    return cur.rowcount


def _get_or_404(scrim_id: int) -> sqlite3.Row:
    row = get_db().execute("SELECT * FROM scrims WHERE id = ?", (scrim_id,)).fetchone()
    if row is None:
        raise ScrimError("Scrim not found.", status=404)
    return row


# --- Directed proposals (US2) ---

def create_proposal(actor: str, proposer_team_id: int, opponent_team_id: int,
                    scheduled_at: str, notes: str | None = None) -> int:
    _require_member(actor, proposer_team_id)
    proposer = get_team(proposer_team_id)
    opponent = get_team(opponent_team_id)
    if proposer is None or opponent is None:
        raise ScrimError("Unknown team.")
    if proposer_team_id == opponent_team_id:
        raise ScrimError("You cannot propose a scrim to your own team.")
    if proposer["format"] != opponent["format"]:
        raise ScrimError("Scrims must be between two teams of the same format.")
    when = _require_future(scheduled_at)
    return _insert(proposer["format"], when, "proposal", proposer_team_id,
                   opponent_team_id, "pending", actor, notes)


def accept(actor: str, scrim_id: int) -> None:
    scrim = _get_or_404(scrim_id)
    if scrim["status"] != "pending":
        raise ScrimError("Only a pending proposal can be accepted.")
    _require_member(actor, scrim["opponent_team_id"])
    _set_status(scrim_id, "confirmed")


def decline(actor: str, scrim_id: int) -> None:
    scrim = _get_or_404(scrim_id)
    if scrim["status"] != "pending":
        raise ScrimError("Only a pending proposal can be declined.")
    _require_member(actor, scrim["opponent_team_id"])
    _set_status(scrim_id, "declined")
    _release_server_credit(scrim_id)


def withdraw(actor: str, scrim_id: int) -> None:
    scrim = _get_or_404(scrim_id)
    if scrim["status"] != "pending":
        raise ScrimError("Only a pending proposal can be withdrawn.")
    _require_member(actor, scrim["proposer_team_id"])
    _set_status(scrim_id, "cancelled")
    _release_server_credit(scrim_id)


def cancel(actor: str, scrim_id: int) -> None:
    """Either participant cancels a confirmed scrim; the row is kept (FR-015)."""
    scrim = _get_or_404(scrim_id)
    if scrim["status"] != "confirmed":
        raise ScrimError("Only a confirmed scrim can be cancelled.")
    if not (is_member(actor, scrim["proposer_team_id"])
            or (scrim["opponent_team_id"] and is_member(actor, scrim["opponent_team_id"]))):
        raise ScrimForbidden()
    _set_status(scrim_id, "cancelled")
    _release_server_credit(scrim_id)


def _release_server_credit(scrim_id: int) -> None:
    """A scrim that will not happen must not cost its team a credit (FR-056, FR-057).

    Imported lazily: servers_store imports credits, which would otherwise make a cycle
    with this module.
    """
    from . import servers_store
    servers_store.release_if_unstarted(scrim_id)


# --- Open listings (US3) ---

def create_listing(actor: str, team_id: int, scheduled_at: str,
                   notes: str | None = None) -> int:
    _require_member(actor, team_id)
    team = get_team(team_id)
    if team is None:
        raise ScrimError("Unknown team.")
    when = _require_future(scheduled_at)
    return _insert(team["format"], when, "listing", team_id, None, "open", actor, notes)


def claim(actor: str, scrim_id: int, claiming_team_id: int) -> None:
    scrim = _get_or_404(scrim_id)
    if scrim["origin"] != "listing":
        raise ScrimError("Only an open listing can be claimed.")
    _require_member(actor, claiming_team_id)
    claiming = get_team(claiming_team_id)
    if claiming is None:
        raise ScrimError("Unknown team.")
    if claiming_team_id == scrim["proposer_team_id"]:
        raise ScrimError("You cannot claim your own listing.")
    if claiming["format"] != scrim["format"]:
        raise ScrimError("Scrims must be between two teams of the same format.")
    # Atomic first-claim-wins (FR-011); an expired listing (past scheduled_at)
    # also stops matching, so it can never be claimed even mid-race (004 FR-003).
    db = get_db()
    now = utc_now()
    cur = db.execute(
        """UPDATE scrims SET status = 'confirmed', opponent_team_id = ?, updated_at = ?
           WHERE id = ? AND status = 'open' AND scheduled_at > ?""",
        (claiming_team_id, now, scrim_id, now))
    db.commit()
    if cur.rowcount == 0:
        raise ScrimError("This listing is no longer available.", status=409)


def cancel_listing(actor: str, scrim_id: int) -> None:
    scrim = _get_or_404(scrim_id)
    if scrim["origin"] != "listing" or scrim["status"] != "open":
        raise ScrimError("Only an open listing can be cancelled.")
    _require_member(actor, scrim["proposer_team_id"])
    _set_status(scrim_id, "cancelled")
    _release_server_credit(scrim_id)


# --- Queries (FR-014) ---

_SELECT = """
    SELECT s.*, pt.name AS proposer_name, pt.tag AS proposer_tag,
           pt.division_name AS proposer_division,
           ot.name AS opponent_name, ot.tag AS opponent_tag,
           EXISTS(SELECT 1 FROM rgl_memberships m
                  WHERE m.rgl_team_id = s.opponent_team_id) AS opponent_on_platform
    FROM scrims s
    JOIN rgl_teams pt ON pt.rgl_team_id = s.proposer_team_id
    LEFT JOIN rgl_teams ot ON ot.rgl_team_id = s.opponent_team_id
"""

_MY_TEAMS = "(SELECT rgl_team_id FROM rgl_memberships WHERE steam_id = ?)"


def get_scrim(scrim_id: int) -> sqlite3.Row | None:
    return get_db().execute(_SELECT + " WHERE s.id = ?", (scrim_id,)).fetchone()


def get_scrim_for_viewer(scrim_id: int, steam_id: str) -> sqlite3.Row | None:
    """Detail-page visibility (004 research §6): an open, *future* listing is
    visible to any RGL-linked user (that's what the dashboard exposes); anything
    else — claimed, cancelled, expired, or proposal-origin — only to members of a
    participating team. None means render 404."""
    scrim = get_scrim(scrim_id)
    if scrim is None:
        return None
    if (scrim["origin"] == "listing" and scrim["status"] == "open"
            and scrim["scheduled_at"] > utc_now()):
        return scrim
    if is_member(steam_id, scrim["proposer_team_id"]):
        return scrim
    if scrim["opponent_team_id"] and is_member(steam_id, scrim["opponent_team_id"]):
        return scrim
    return None


def incoming_pending(steam_id: str) -> list[sqlite3.Row]:
    return get_db().execute(
        _SELECT + f" WHERE s.status = 'pending' AND s.opponent_team_id IN {_MY_TEAMS}"
        " ORDER BY s.scheduled_at", (steam_id,)).fetchall()


def outgoing_pending(steam_id: str) -> list[sqlite3.Row]:
    return get_db().execute(
        _SELECT + f" WHERE s.status = 'pending' AND s.proposer_team_id IN {_MY_TEAMS}"
        " ORDER BY s.scheduled_at", (steam_id,)).fetchall()


def upcoming_confirmed(steam_id: str) -> list[sqlite3.Row]:
    return get_db().execute(
        _SELECT + f""" WHERE s.status = 'confirmed'
            AND (s.proposer_team_id IN {_MY_TEAMS} OR s.opponent_team_id IN {_MY_TEAMS})
            AND s.scheduled_at >= ?
            ORDER BY s.scheduled_at""",
        (steam_id, steam_id, utc_now())).fetchall()


def my_open_listings(steam_id: str) -> list[sqlite3.Row]:
    """The user's own open listings, excluding expired ones (004 FR-003)."""
    return get_db().execute(
        _SELECT + f" WHERE s.status = 'open' AND s.proposer_team_id IN {_MY_TEAMS}"
        " AND s.scheduled_at > ? ORDER BY s.scheduled_at",
        (steam_id, utc_now())).fetchall()


def open_listings(format_: str | None = None) -> list[sqlite3.Row]:
    """Open future listings (all teams). Expiry is read-side: rows whose
    scheduled_at has passed simply stop matching (004 FR-003 / SC-002)."""
    query = _SELECT + " WHERE s.status = 'open' AND s.scheduled_at > ?"
    params: tuple = (utc_now(),)
    if format_:
        query += " AND s.format = ?"
        params += (format_,)
    return get_db().execute(query + " ORDER BY s.scheduled_at", params).fetchall()
