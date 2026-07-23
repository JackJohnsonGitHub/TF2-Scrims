"""Persistence for the RGL link, teams, and memberships.

Teams are first-class shared rows keyed by RGL's global team id; membership rows
are what authorize a user to act for a team (FR-016). Memberships are rebuilt on
every link/refresh so teams the user left drop out. Unlink removes the link and
the user's memberships but keeps the shared `rgl_teams` rows (other members and
existing scrims still reference them).
"""
import sqlite3
from datetime import datetime, timezone

from .db import get_db
from .rgl import RglProfile


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def save_link(steam_id: str, profile: RglProfile) -> str:
    """Upsert the link + teams and rebuild the user's memberships from a fetched
    profile (outcome `ok` or `no_profile` — never `unavailable`, the caller keeps
    prior state on outages). Returns the stored link state."""
    if profile.outcome == "no_profile":
        state = "no_profile"
    elif profile.teams:
        state = "linked"
    else:
        state = "no_team"

    db = get_db()
    now = utc_now()
    db.execute(
        """INSERT INTO rgl_links (steam_id, profile_name, state, is_verified, is_banned,
                                  is_on_probation, linked_at, last_refreshed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(steam_id) DO UPDATE SET
               profile_name=excluded.profile_name, state=excluded.state,
               is_verified=excluded.is_verified, is_banned=excluded.is_banned,
               is_on_probation=excluded.is_on_probation,
               last_refreshed_at=excluded.last_refreshed_at""",
        (steam_id, profile.name, state, int(profile.is_verified),
         int(profile.is_banned), int(profile.is_on_probation), now, now),
    )
    for team in profile.teams:
        db.execute(
            """INSERT INTO rgl_teams (rgl_team_id, name, tag, format, division_name,
                                      season_id, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(rgl_team_id) DO UPDATE SET
                   name=excluded.name, tag=excluded.tag, format=excluded.format,
                   division_name=excluded.division_name, season_id=excluded.season_id,
                   updated_at=excluded.updated_at""",
            (team.rgl_team_id, team.name, team.tag, team.format,
             team.division_name, team.season_id, now),
        )
    # Rebuild memberships: drops teams the user left since the last refresh.
    db.execute("DELETE FROM rgl_memberships WHERE steam_id = ?", (steam_id,))
    for team in profile.teams:
        db.execute(
            "INSERT INTO rgl_memberships (steam_id, rgl_team_id) VALUES (?, ?)",
            (steam_id, team.rgl_team_id),
        )
    db.commit()
    return state


def get_link(steam_id: str) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM rgl_links WHERE steam_id = ?", (steam_id,)
    ).fetchone()


def get_user_teams(steam_id: str) -> list[sqlite3.Row]:
    """Teams the user is currently on (their acting authority), ordered by format."""
    return get_db().execute(
        """SELECT t.* FROM rgl_teams t
           JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
           WHERE m.steam_id = ? ORDER BY t.format, t.name""",
        (steam_id,),
    ).fetchall()


def get_team(rgl_team_id: int) -> sqlite3.Row | None:
    return get_db().execute(
        "SELECT * FROM rgl_teams WHERE rgl_team_id = ?", (rgl_team_id,)
    ).fetchone()


def all_teams() -> list[sqlite3.Row]:
    """Every team known to the platform (potential opponents), ordered by format."""
    return get_db().execute(
        "SELECT * FROM rgl_teams ORDER BY format, name"
    ).fetchall()


def is_member(steam_id: str, rgl_team_id: int) -> bool:
    """The authority check (FR-016): a user may act for a team iff a membership
    row exists."""
    row = get_db().execute(
        "SELECT 1 FROM rgl_memberships WHERE steam_id = ? AND rgl_team_id = ?",
        (steam_id, rgl_team_id),
    ).fetchone()
    return row is not None


def unlink(steam_id: str) -> None:
    db = get_db()
    db.execute("DELETE FROM rgl_memberships WHERE steam_id = ?", (steam_id,))
    db.execute("DELETE FROM rgl_links WHERE steam_id = ?", (steam_id,))
    db.commit()
