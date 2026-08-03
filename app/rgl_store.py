"""Persistence for the RGL link, teams, and memberships.

Teams are first-class shared rows keyed by RGL's global team id; membership rows
are what authorize a user to act for a team (FR-016). Memberships are rebuilt on
every link/refresh so teams the user left drop out. Unlink removes the link and
the user's memberships but keeps the shared `rgl_teams` rows (other members and
existing scrims still reference them).
"""
import json
from datetime import datetime, timedelta, timezone

from flask import current_app

from . import rgl
from .db import get_db
from .rgl import RglProfile, RglRosterPlayer


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
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT(rgl_team_id) DO UPDATE SET
                   name=excluded.name, tag=excluded.tag, format=excluded.format,
                   division_name=excluded.division_name, season_id=excluded.season_id,
                   updated_at=excluded.updated_at""",
            (team.rgl_team_id, team.name, team.tag, team.format,
             team.division_name, team.season_id, now),
        )
    # Rebuild memberships: drops teams the user left since the last refresh.
    db.execute("DELETE FROM rgl_memberships WHERE steam_id = %s", (steam_id,))
    for team in profile.teams:
        db.execute(
            "INSERT INTO rgl_memberships (steam_id, rgl_team_id) VALUES (%s, %s)",
            (steam_id, team.rgl_team_id),
        )
    db.commit()
    return state


def get_link(steam_id: str) -> dict | None:
    return get_db().execute(
        "SELECT * FROM rgl_links WHERE steam_id = %s", (steam_id,)
    ).fetchone()


def get_user_teams(steam_id: str) -> list[dict]:
    """Teams the user is currently on (their acting authority), ordered by format."""
    return get_db().execute(
        """SELECT t.* FROM rgl_teams t
           JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
           WHERE m.steam_id = %s ORDER BY t.format, t.name""",
        (steam_id,),
    ).fetchall()


def get_team(rgl_team_id: int) -> dict | None:
    return get_db().execute(
        "SELECT * FROM rgl_teams WHERE rgl_team_id = %s", (rgl_team_id,)
    ).fetchone()


def all_teams() -> list[dict]:
    """Every team known to the platform (potential opponents), ordered by format."""
    return get_db().execute(
        "SELECT * FROM rgl_teams ORDER BY format, name"
    ).fetchall()


def is_member(steam_id: str, rgl_team_id: int) -> bool:
    """The authority check (FR-016): a user may act for a team iff a membership
    row exists."""
    row = get_db().execute(
        "SELECT 1 FROM rgl_memberships WHERE steam_id = %s AND rgl_team_id = %s",
        (steam_id, rgl_team_id),
    ).fetchone()
    return row is not None


def unlink(steam_id: str) -> None:
    db = get_db()
    db.execute("DELETE FROM rgl_memberships WHERE steam_id = %s", (steam_id,))
    db.execute("DELETE FROM rgl_links WHERE steam_id = %s", (steam_id,))
    db.commit()


# --- Team rosters (feature 004) ---
# Cached player lists keyed by RGL team id, refreshed at most every
# RGL_ROSTER_TTL_SECONDS and only from listing-detail views. A failed fetch never
# touches the cache or the stamp (stale-if-error, research §2).

def save_roster(rgl_team_id: int, players: list[RglRosterPlayer]) -> None:
    """Atomically replace a team's cached roster and stamp the successful fetch."""
    db = get_db()
    now = utc_now()
    db.execute("DELETE FROM rgl_rosters WHERE rgl_team_id = %s", (rgl_team_id,))
    for p in players:
        db.execute(
            """INSERT INTO rgl_rosters (rgl_team_id, steam_id, name, is_leader)
               VALUES (%s, %s, %s, %s)""",
            (rgl_team_id, p.steam_id, p.name, int(p.is_leader)),
        )
    db.execute(
        """INSERT INTO rgl_roster_meta (rgl_team_id, fetched_at) VALUES (%s, %s)
           ON CONFLICT(rgl_team_id) DO UPDATE SET fetched_at = excluded.fetched_at""",
        (rgl_team_id, now),
    )
    db.commit()


def get_roster(rgl_team_id: int) -> list[dict]:
    return get_db().execute(
        """SELECT * FROM rgl_rosters WHERE rgl_team_id = %s
           ORDER BY is_leader DESC, lower(name)""",
        (rgl_team_id,),
    ).fetchall()


def roster_fetched_at(rgl_team_id: int) -> str | None:
    row = get_db().execute(
        "SELECT fetched_at FROM rgl_roster_meta WHERE rgl_team_id = %s",
        (rgl_team_id,),
    ).fetchone()
    return row["fetched_at"] if row else None


def ensure_roster(rgl_team_id: int) -> tuple[list[dict], str | None]:
    """Return (cached roster, fetched_at), refreshing from RGL when the stamp is
    missing or older than the TTL. Empty rows with a None stamp means the roster
    is unknown (never fetched successfully) — render the friendly notice."""
    ttl = current_app.config["RGL_ROSTER_TTL_SECONDS"]
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl)).isoformat(
        timespec="seconds")
    stamp = roster_fetched_at(rgl_team_id)
    if stamp is None or stamp < cutoff:
        result = rgl.fetch_team_roster(rgl_team_id)
        if result.outcome == "ok":
            save_roster(rgl_team_id, result.players)
    return get_roster(rgl_team_id), roster_fetched_at(rgl_team_id)


# --- Season directory (feature 004 US4) ---
# RGL's season endpoint yields only team ids + a division sort map; names come from
# per-team fetches, so the directory hydrates in bounded batches (research §8).

def get_season(season_id: int) -> dict | None:
    return get_db().execute(
        "SELECT * FROM rgl_seasons WHERE season_id = %s", (season_id,)
    ).fetchone()


def ensure_season(season_id: int) -> dict | None:
    """Fetch/refresh the season header + participation list within the directory
    TTL. A failed refresh keeps the cached season (stale-if-error); None means
    nothing cached and RGL unreachable — render the friendly notice."""
    ttl = current_app.config["RGL_DIRECTORY_TTL_SECONDS"]
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl)).isoformat(
        timespec="seconds")
    row = get_season(season_id)
    if row is not None and row["fetched_at"] >= cutoff:
        return row

    season = rgl.fetch_season(season_id)
    if season.outcome != "ok":
        return row  # stale-if-error (None when never fetched)

    db = get_db()
    db.execute(
        """INSERT INTO rgl_seasons (season_id, name, format, division_sorting, fetched_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT(season_id) DO UPDATE SET name = excluded.name,
               format = excluded.format, division_sorting = excluded.division_sorting,
               fetched_at = excluded.fetched_at""",
        (season_id, season.name, season.format,
         json.dumps(season.division_sorting), utc_now()),
    )
    for team_id in season.team_ids:
        db.execute(
            "INSERT INTO rgl_season_teams (season_id, rgl_team_id) VALUES (%s, %s)"
            " ON CONFLICT DO NOTHING",
            (season_id, team_id),
        )
    db.commit()
    return get_season(season_id)


def season_progress(season_id: int) -> tuple[int, int]:
    row = get_db().execute(
        """SELECT COUNT(hydrated_at) AS done, COUNT(*) AS total
           FROM rgl_season_teams WHERE season_id = %s""",
        (season_id,),
    ).fetchone()
    return row["done"], row["total"]


def hydrate_season_teams(season_id: int, batch: int) -> int:
    """Hydrate up to `batch` pending directory teams via the team endpoint,
    upserting each into the shared `rgl_teams` identity store. Stops early on an
    RGL outage (pending rows retry on a later request); dead teams (404) are
    stamped with no division so they drop out instead of retrying forever.
    Returns how many teams were hydrated."""
    season = get_season(season_id)
    if season is None:
        return 0
    pending = get_db().execute(
        """SELECT rgl_team_id FROM rgl_season_teams
           WHERE season_id = %s AND hydrated_at IS NULL
           ORDER BY rgl_team_id LIMIT %s""",
        (season_id, batch),
    ).fetchall()

    db = get_db()
    hydrated = 0
    now = utc_now()
    for row in pending:
        team_id = row["rgl_team_id"]
        summary = rgl.fetch_team_summary(team_id)
        if summary.outcome == "unavailable":
            break  # RGL is down — don't hammer the rest of the batch
        if summary.outcome == "ok":
            db.execute(
                """INSERT INTO rgl_teams (rgl_team_id, name, tag, format, division_name,
                                          season_id, updated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT(rgl_team_id) DO UPDATE SET name = excluded.name,
                       tag = excluded.tag, format = excluded.format,
                       division_name = excluded.division_name,
                       season_id = excluded.season_id, updated_at = excluded.updated_at""",
                (team_id, summary.name, summary.tag, season["format"],
                 summary.division_name, season_id, now),
            )
            hydrated += 1
        # ok and no_team both stamp the row; no_team keeps division_id NULL so the
        # browser skips it.
        db.execute(
            """UPDATE rgl_season_teams SET division_id = %s, hydrated_at = %s
               WHERE season_id = %s AND rgl_team_id = %s""",
            (summary.division_id if summary.outcome == "ok" else None, now,
             season_id, team_id),
        )
    db.commit()
    return hydrated


def division_browser(season_id: int, division_id: int | None = None
                     ) -> tuple[list[dict], list[dict]]:
    """Hydrated divisions (ordered by the season's divisionSorting rank) and, when
    a division is chosen, its teams with on-platform flags."""
    season = get_season(season_id)
    sorting = json.loads(season["division_sorting"]) if season else {}
    divisions = [
        dict(r)
        for r in get_db().execute(
            """SELECT st.division_id, t.division_name, COUNT(*) AS team_count
               FROM rgl_season_teams st
               JOIN rgl_teams t ON t.rgl_team_id = st.rgl_team_id
               WHERE st.season_id = %s AND st.division_id IS NOT NULL
               GROUP BY st.division_id, t.division_name""",
            (season_id,),
        )
    ]
    divisions.sort(key=lambda d: (sorting.get(str(d["division_id"]), 1_000_000),
                                  d["division_name"] or ""))
    teams: list[dict] = []
    if division_id is not None:
        teams = get_db().execute(
            """SELECT t.*, EXISTS(SELECT 1 FROM rgl_memberships m
                                  WHERE m.rgl_team_id = t.rgl_team_id) AS on_platform
               FROM rgl_season_teams st
               JOIN rgl_teams t ON t.rgl_team_id = st.rgl_team_id
               WHERE st.season_id = %s AND st.division_id = %s
               ORDER BY lower(t.name)""",
            (season_id, division_id),
        ).fetchall()
    return divisions, teams


def search_teams(format_: str, query: str, season_id: int | None,
                 limit: int) -> list[dict]:
    """Name/tag search over the teams the propose picker can reach: everything
    hydrated for the proposing team's season, plus every on-platform team of that
    format (a team can be on the platform before its season is hydrated).

    A division is a poor index for "I know who I want to play" — you have to already
    know which division they're in — so search is the primary way into the directory
    and the division filter is the fallback for browsing. `season_id = NULL` matches
    nothing, so a team with no season degrades to on-platform teams only.
    """
    like = f"%{query.strip()}%"
    return get_db().execute(
        """SELECT t.*, EXISTS(SELECT 1 FROM rgl_memberships m
                              WHERE m.rgl_team_id = t.rgl_team_id) AS on_platform
           FROM rgl_teams t
           WHERE t.format = %s
             AND (t.season_id = %s
                  OR EXISTS(SELECT 1 FROM rgl_memberships m
                            WHERE m.rgl_team_id = t.rgl_team_id))
             AND (t.name ILIKE %s OR COALESCE(t.tag, '') ILIKE %s)
           ORDER BY on_platform DESC, lower(t.name)
           LIMIT %s""",
        (format_, season_id, like, like, limit),
    ).fetchall()


def team_on_platform(rgl_team_id: int) -> bool:
    """True when at least one member of the team has an account here (FR-019/020)."""
    row = get_db().execute(
        "SELECT 1 FROM rgl_memberships WHERE rgl_team_id = %s LIMIT 1",
        (rgl_team_id,),
    ).fetchone()
    return row is not None


def platform_teams(format_: str | None = None) -> list[dict]:
    """Teams with at least one member on the platform — the propose form's quick
    pick. The division browser is the path to everything else (research §9)."""
    query = """SELECT DISTINCT t.* FROM rgl_teams t
               JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id"""
    params: tuple = ()
    if format_:
        query += " WHERE t.format = %s"
        params = (format_,)
    return get_db().execute(query + " ORDER BY t.format, t.name", params).fetchall()
