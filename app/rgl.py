"""RGL public API client (api.rgl.gg — public, keyless).

One endpoint gives everything linking needs: `/v0/profile/{steamid64}` returns the
persona name, status flags, and `currentTeams` keyed by format. Outcomes are mapped
explicitly and never raised to the caller (FR-006 / SC-008): `ok` (profile fetched,
teams possibly empty), `no_profile` (404/empty), `unavailable` (timeout/5xx/network).
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
