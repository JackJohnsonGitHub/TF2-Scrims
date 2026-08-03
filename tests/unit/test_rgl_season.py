"""Unit tests for the RGL season client (app/rgl.py) and the season directory
store (app/rgl_store.py) — US4 division browser. HTTP mocked; shapes per
research.md §8 (verified live: seasons carry ids only, teams carry names)."""
from datetime import datetime, timedelta, timezone

import requests

from app import rgl
from tests.conftest import rgl_team


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


SEASON_PAYLOAD = {
    "name": "6s Season 20",
    "formatName": "Sixes",
    "regionName": "NA Sixes",
    "divisionSorting": {"9001": 0, "9002": 1},
    "participatingTeams": [601, 602, 603],
}

TEAM_SUMMARY_PAYLOAD = {
    "teamId": 601,
    "seasonId": 140,
    "divisionId": 9001,
    "divisionName": "Invite",
    "tag": "RVL",
    "name": "Rivals",
    "players": [],
}


# --- fetch_season (client) ---

def test_parses_season(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=SEASON_PAYLOAD))
    with app.app_context():
        season = rgl.fetch_season(140)
    assert season.outcome == "ok"
    assert season.name == "6s Season 20"
    assert season.format == "sixes"
    assert season.division_sorting == {"9001": 0, "9002": 1}
    assert season.team_ids == [601, 602, 603]


def test_season_404_maps_to_no_season(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=404))
    with app.app_context():
        assert rgl.fetch_season(1).outcome == "no_season"


def test_season_errors_map_to_unavailable(app, monkeypatch):
    def _raise(url, timeout):
        raise requests.Timeout("slow")
    monkeypatch.setattr(rgl.requests, "get", _raise)
    with app.app_context():
        assert rgl.fetch_season(1).outcome == "unavailable"
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=502))
    with app.app_context():
        assert rgl.fetch_season(1).outcome == "unavailable"
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(bad_json=True))
    with app.app_context():
        assert rgl.fetch_season(1).outcome == "unavailable"


def test_parses_team_summary(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=TEAM_SUMMARY_PAYLOAD))
    with app.app_context():
        summary = rgl.fetch_team_summary(601)
    assert summary.outcome == "ok"
    assert (summary.name, summary.tag) == ("Rivals", "RVL")
    assert (summary.division_id, summary.division_name) == (9001, "Invite")


def test_team_summary_404_maps_to_no_team(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=404))
    with app.app_context():
        assert rgl.fetch_team_summary(9990001).outcome == "no_team"


# --- season directory store ---

def ok_season(team_ids=(601, 602, 603), fmt="Sixes",
              sorting={"9001": 0, "9002": 1}):
    from app.rgl import RglSeason
    return RglSeason(outcome="ok", name="6s Season 20",
                     format=fmt.lower(), division_sorting=dict(sorting),
                     team_ids=list(team_ids))


def summary_for(team_id, division_id=9001, division_name="Invite"):
    from app.rgl import RglTeamSummary
    return RglTeamSummary(outcome="ok", rgl_team_id=team_id,
                          name=f"Team {team_id}", tag=f"T{team_id}",
                          division_id=division_id, division_name=division_name)


def test_ensure_season_fetches_and_persists(app, monkeypatch):
    from app.db import get_db
    from app.rgl_store import ensure_season
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season())
    with app.test_request_context():
        row = ensure_season(140)
        assert row is not None and row["format"] == "sixes"
        pending = get_db().execute(
            "SELECT COUNT(*) c FROM rgl_season_teams WHERE season_id = 140"
            " AND hydrated_at IS NULL").fetchone()["c"]
    assert pending == 3


def test_ensure_season_respects_ttl(app, monkeypatch):
    from app.rgl_store import ensure_season

    calls = []
    def _fetch(sid):
        calls.append(sid)
        return ok_season()
    monkeypatch.setattr("app.rgl.fetch_season", _fetch)
    with app.test_request_context():
        ensure_season(140)
        ensure_season(140)  # fresh — no second fetch
    assert calls == [140]


def test_ensure_season_stale_if_error(app, monkeypatch):
    from app.db import get_db
    from app.rgl import RglSeason
    from app.rgl_store import ensure_season
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season())
    stale = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="seconds")
    with app.test_request_context():
        ensure_season(140)
        get_db().execute("UPDATE rgl_seasons SET fetched_at = %s", (stale,))
        get_db().commit()
        monkeypatch.setattr("app.rgl.fetch_season",
                            lambda sid: RglSeason(outcome="unavailable"))
        row = ensure_season(140)  # failed refresh keeps the cached season
        assert row is not None and row["name"] == "6s Season 20"


def test_ensure_season_cold_failure_returns_none(app, monkeypatch):
    from app.rgl import RglSeason
    from app.rgl_store import ensure_season
    monkeypatch.setattr("app.rgl.fetch_season",
                        lambda sid: RglSeason(outcome="unavailable"))
    with app.test_request_context():
        assert ensure_season(140) is None


def test_hydrate_is_bounded_and_upserts_teams(app, monkeypatch):
    from app.rgl_store import ensure_season, get_team, hydrate_season_teams, season_progress
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season())
    calls = []
    def _summary(tid):
        calls.append(tid)
        return summary_for(tid)
    monkeypatch.setattr("app.rgl.fetch_team_summary", _summary)
    with app.test_request_context():
        ensure_season(140)
        hydrated = hydrate_season_teams(140, batch=2)
        assert hydrated == 2 and len(calls) == 2
        assert season_progress(140) == (2, 3)
        team = get_team(calls[0])
        assert team is not None
        assert team["format"] == "sixes"        # format comes from the season
        assert team["division_name"] == "Invite"
        assert team["season_id"] == 140


def test_hydrate_stops_on_outage_and_leaves_pending(app, monkeypatch):
    from app.rgl import RglTeamSummary
    from app.rgl_store import ensure_season, hydrate_season_teams, season_progress
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season())
    calls = []
    def _summary(tid):
        calls.append(tid)
        return RglTeamSummary(outcome="unavailable")
    monkeypatch.setattr("app.rgl.fetch_team_summary", _summary)
    with app.test_request_context():
        ensure_season(140)
        assert hydrate_season_teams(140, batch=3) == 0
        assert len(calls) == 1                  # stop after the first failure
        assert season_progress(140) == (0, 3)   # nothing falsely marked hydrated


def test_hydrate_marks_dead_teams_and_browser_skips_them(app, monkeypatch):
    from app.rgl import RglTeamSummary
    from app.rgl_store import division_browser, ensure_season, hydrate_season_teams
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season(team_ids=(601, 999)))
    def _summary(tid):
        if tid == 999:
            return RglTeamSummary(outcome="no_team")  # deleted team → don't retry forever
        return summary_for(tid)
    monkeypatch.setattr("app.rgl.fetch_team_summary", _summary)
    with app.test_request_context():
        ensure_season(140)
        assert hydrate_season_teams(140, batch=10) == 1
        divisions, _ = division_browser(140)
        assert sum(d["team_count"] for d in divisions) == 1  # 999 excluded


def test_division_browser_groups_and_orders(app, monkeypatch):
    from app.rgl_store import division_browser, ensure_season, hydrate_season_teams
    monkeypatch.setattr("app.rgl.fetch_season",
                        lambda sid: ok_season(sorting={"9001": 5, "9002": 1}))
    def _summary(tid):
        if tid == 603:
            return summary_for(tid, division_id=9002, division_name="Main")
        return summary_for(tid, division_id=9001, division_name="Invite")
    monkeypatch.setattr("app.rgl.fetch_team_summary", _summary)
    with app.test_request_context():
        ensure_season(140)
        hydrate_season_teams(140, batch=10)
        divisions, _ = division_browser(140)
        # ordered by divisionSorting rank: Main (1) before Invite (5)
        assert [d["division_name"] for d in divisions] == ["Main", "Invite"]
        assert [d["team_count"] for d in divisions] == [1, 2]
        _, teams = division_browser(140, division_id=9001)
        assert [t["rgl_team_id"] for t in teams] == [601, 602]
        assert all(t["on_platform"] == 0 for t in teams)


def test_platform_teams_scopes_to_membership(app, link_team, monkeypatch):
    from app.rgl_store import ensure_season, hydrate_season_teams, platform_teams
    link_team("76561198000000001", [rgl_team(101, "Alpha", "ALP", "sixes")])
    monkeypatch.setattr("app.rgl.fetch_season", lambda sid: ok_season(team_ids=(601,)))
    monkeypatch.setattr("app.rgl.fetch_team_summary", lambda tid: summary_for(tid))
    with app.test_request_context():
        ensure_season(140)
        hydrate_season_teams(140, batch=10)   # Team 601 now in rgl_teams, no members
        ids = [t["rgl_team_id"] for t in platform_teams("sixes")]
    assert ids == [101]  # membership-backed only — hydrated league teams excluded