"""RGL public API client (api.rgl.gg — public, keyless).

`/v0/profile/{steamid64}` returns the persona name, status flags, and `currentTeams`
keyed by format (feature 003). `/v0/teams/{teamId}` returns the team's `players[]` —
the current roster is the entries whose `leftAt` is null (feature 004, shape verified
live in specs/004-scrims-dashboard/research.md §1). Outcomes are mapped explicitly
and never raised to the caller: `ok`, `no_profile`/`no_team` (404/empty),
`unavailable` (timeout/5xx/network/malformed).
"""
from dataclasses import dataclass, field

import requests
from flask import current_app

FORMATS = ("sixes", "highlander", "prolander")


@dataclass
class RglTeam:
    rgl_team_id: int
    name: str
    tag: str | None
    format: str  # one of FORMATS
    division_name: str | None
    season_id: int | None


@dataclass
class RglProfile:
    outcome: str  # "ok" | "no_profile" | "unavailable"
    name: str | None = None
    is_verified: bool = False
    is_banned: bool = False
    is_on_probation: bool = False
    teams: list[RglTeam] = field(default_factory=list)


@dataclass
class RglRosterPlayer:
    steam_id: str
    name: str
    is_leader: bool = False


@dataclass
class RglTeamRoster:
    outcome: str  # "ok" | "no_team" | "unavailable"
    players: list[RglRosterPlayer] = field(default_factory=list)


@dataclass
class RglSeason:
    """A season header (US4): division sort map and participating team ids only —
    RGL's season endpoint carries no team or division names (research §8)."""
    outcome: str  # "ok" | "no_season" | "unavailable"
    name: str | None = None
    format: str | None = None  # one of FORMATS, from formatName, else None
    division_sorting: dict = field(default_factory=dict)  # division id (str) → rank
    team_ids: list[int] = field(default_factory=list)


@dataclass
class RglTeamSummary:
    """Team display fields for directory hydration (same endpoint as rosters)."""
    outcome: str  # "ok" | "no_team" | "unavailable"
    rgl_team_id: int | None = None
    name: str | None = None
    tag: str | None = None
    division_id: int | None = None
    division_name: str | None = None


def fetch_profile(steam_id: str) -> RglProfile:
    """Fetch the RGL profile for a SteamID64. Never raises; see module docstring
    for the outcome mapping."""
    url = f"{current_app.config['RGL_API_BASE']}/profile/{steam_id}"
    try:
        resp = requests.get(url, timeout=current_app.config["RGL_TIMEOUT_SECONDS"])
    except requests.RequestException:
        return RglProfile(outcome="unavailable")

    if resp.status_code == 404:
        return RglProfile(outcome="no_profile")
    if resp.status_code != 200:
        return RglProfile(outcome="unavailable")

    try:
        data = resp.json()
    except ValueError:
        return RglProfile(outcome="unavailable")
    if not data or not data.get("name"):
        return RglProfile(outcome="no_profile")

    status = data.get("status") or {}
    current = data.get("currentTeams") or {}
    teams = []
    for fmt in FORMATS:
        raw = current.get(fmt)
        if raw:
            teams.append(
                RglTeam(
                    rgl_team_id=raw["id"],
                    name=raw.get("name") or f"Team {raw['id']}",
                    tag=raw.get("tag"),
                    format=fmt,
                    division_name=raw.get("divisionName"),
                    season_id=raw.get("seasonId"),
                )
            )
    return RglProfile(
        outcome="ok",
        name=data["name"],
        is_verified=bool(status.get("isVerified")),
        is_banned=bool(status.get("isBanned")),
        is_on_probation=bool(status.get("isOnProbation")),
        teams=teams,
    )


def fetch_season(season_id: int) -> RglSeason:
    """Fetch a season header by RGL season id. Never raises."""
    url = f"{current_app.config['RGL_API_BASE']}/seasons/{season_id}"
    try:
        resp = requests.get(url, timeout=current_app.config["RGL_TIMEOUT_SECONDS"])
    except requests.RequestException:
        return RglSeason(outcome="unavailable")

    if resp.status_code == 404:
        return RglSeason(outcome="no_season")
    if resp.status_code != 200:
        return RglSeason(outcome="unavailable")

    try:
        data = resp.json()
    except ValueError:
        return RglSeason(outcome="unavailable")
    if not data or not data.get("name"):
        return RglSeason(outcome="no_season")

    format_name = (data.get("formatName") or "").lower()
    return RglSeason(
        outcome="ok",
        name=data["name"],
        format=format_name if format_name in FORMATS else None,
        division_sorting=data.get("divisionSorting") or {},
        team_ids=[int(t) for t in data.get("participatingTeams") or []],
    )


def fetch_team_summary(team_id: int) -> RglTeamSummary:
    """Fetch a team's display fields (name/tag/division) for directory hydration.
    Never raises."""
    url = f"{current_app.config['RGL_API_BASE']}/teams/{team_id}"
    try:
        resp = requests.get(url, timeout=current_app.config["RGL_TIMEOUT_SECONDS"])
    except requests.RequestException:
        return RglTeamSummary(outcome="unavailable")

    if resp.status_code == 404:
        return RglTeamSummary(outcome="no_team")
    if resp.status_code != 200:
        return RglTeamSummary(outcome="unavailable")

    try:
        data = resp.json()
    except ValueError:
        return RglTeamSummary(outcome="unavailable")
    if not data or not data.get("name"):
        return RglTeamSummary(outcome="no_team")

    return RglTeamSummary(
        outcome="ok",
        rgl_team_id=int(data.get("teamId") or team_id),
        name=data["name"],
        tag=data.get("tag"),
        division_id=data.get("divisionId"),
        division_name=data.get("divisionName"),
    )


def fetch_team_roster(team_id: int) -> RglTeamRoster:
    """Fetch a team's current roster by RGL team id. Never raises; departed
    players (non-null `leftAt`) are excluded."""
    url = f"{current_app.config['RGL_API_BASE']}/teams/{team_id}"
    try:
        resp = requests.get(url, timeout=current_app.config["RGL_TIMEOUT_SECONDS"])
    except requests.RequestException:
        return RglTeamRoster(outcome="unavailable")

    if resp.status_code == 404:
        return RglTeamRoster(outcome="no_team")
    if resp.status_code != 200:
        return RglTeamRoster(outcome="unavailable")

    try:
        data = resp.json()
    except ValueError:
        return RglTeamRoster(outcome="unavailable")
    if not data:
        return RglTeamRoster(outcome="no_team")

    players = []
    for raw in data.get("players") or []:
        if raw.get("leftAt") is not None or not raw.get("steamId"):
            continue
        players.append(
            RglRosterPlayer(
                steam_id=str(raw["steamId"]),
                name=raw.get("name") or str(raw["steamId"]),
                is_leader=bool(raw.get("isLeader")),
            )
        )
    return RglTeamRoster(outcome="ok", players=players)
