"""Unit tests for the RGL team-roster client (app/rgl.py) and the roster cache
(app/rgl_store.py) — HTTP mocked, shape per research.md §1 (verified live)."""
from datetime import datetime, timedelta, timezone

import pytest
import requests

from app import rgl


@pytest.fixture(autouse=True)
def _known_teams(app):
    """A roster is only ever cached for a team the app already knows: the sole caller
    of `ensure_roster` passes a scrim's `proposer_team_id`, which is itself
    FK-constrained to `rgl_teams`. These tests drive the cache directly, so the team
    rows they imply now have to exist for real — foreign keys are enforced as of
    feature 005, having been silently ignored before that."""
    from app.db import get_db
    with app.test_request_context():
        db = get_db()
        for team_id in (101, 9990001):
            db.execute(
                "INSERT OR IGNORE INTO rgl_teams (rgl_team_id, name, format, updated_at)"
                " VALUES (?, ?, 'sixes', '2026-07-29T00:00:00+00:00')",
                (team_id, f"Team {team_id}"),
            )
        db.commit()


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


TEAM_PAYLOAD = {
    "teamId": 14959,
    "name": 'What\'s A "Competitive?"',
    "tag": "WAC",
    "divisionName": "Amateur",
    "seasonId": 193,
    "players": [
        {"name": "crazedorangutan", "steamId": "76561198059104274",
         "isLeader": True, "joinedAt": "2026-05-13", "leftAt": None},
        {"name": "TheLazySquid", "steamId": "76561199088088348",
         "isLeader": False, "joinedAt": "2026-05-13", "leftAt": None},
        {"name": "imperial", "steamId": "76561198287352249",
         "isLeader": False, "joinedAt": "2026-05-13", "leftAt": "2026-05-25"},
    ],
}


# --- fetch_team_roster (client) ---

def test_parses_current_players_and_excludes_departed(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=TEAM_PAYLOAD))
    with app.app_context():
        roster = rgl.fetch_team_roster(14959)
    assert roster.outcome == "ok"
    assert [(p.steam_id, p.is_leader) for p in roster.players] == [
        ("76561198059104274", True),
        ("76561199088088348", False),
    ]  # imperial left (leftAt set) and is excluded
    assert roster.players[0].name == "crazedorangutan"


def test_team_404_maps_to_no_team(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=404))
    with app.app_context():
        assert rgl.fetch_team_roster(9990001).outcome == "no_team"


def test_empty_payload_maps_to_no_team(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload={}))
    with app.app_context():
        assert rgl.fetch_team_roster(1).outcome == "no_team"


def test_timeout_maps_to_unavailable(app, monkeypatch):
    def _raise(url, timeout):
        raise requests.Timeout("slow")
    monkeypatch.setattr(rgl.requests, "get", _raise)
    with app.app_context():
        assert rgl.fetch_team_roster(1).outcome == "unavailable"


def test_5xx_maps_to_unavailable(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=502))
    with app.app_context():
        assert rgl.fetch_team_roster(1).outcome == "unavailable"


def test_invalid_json_maps_to_unavailable(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(bad_json=True))
    with app.app_context():
        assert rgl.fetch_team_roster(1).outcome == "unavailable"


def test_players_without_steamid_are_skipped(app, monkeypatch):
    payload = {"name": "T", "players": [
        {"name": "ghost", "steamId": None, "leftAt": None},
        {"name": "real", "steamId": "76561198000000009", "leftAt": None},
    ]}
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=payload))
    with app.app_context():
        roster = rgl.fetch_team_roster(1)
    assert [p.steam_id for p in roster.players] == ["76561198000000009"]


# --- roster cache (store) ---

def players(*specs):
    from app.rgl import RglRosterPlayer
    return [RglRosterPlayer(steam_id=s, name=n, is_leader=lead)
            for s, n, lead in specs]


def test_save_and_get_roster_orders_leaders_first(app):
    from app.rgl_store import get_roster, save_roster
    with app.test_request_context():
        save_roster(101, players(("2", "zed", False), ("1", "amy", True)))
        rows = get_roster(101)
    assert [(r["steam_id"], r["name"], r["is_leader"]) for r in rows] == [
        ("1", "amy", 1), ("2", "zed", 0)]


def test_save_roster_replaces_previous_rows_and_stamps(app):
    from app.rgl_store import get_roster, roster_fetched_at, save_roster
    with app.test_request_context():
        save_roster(101, players(("1", "amy", True), ("2", "zed", False)))
        first_stamp = roster_fetched_at(101)
        save_roster(101, players(("1", "amy", True)))  # zed departed
        rows = get_roster(101)
        assert roster_fetched_at(101) is not None
    assert first_stamp is not None
    assert [r["steam_id"] for r in rows] == ["1"]


def test_ensure_roster_fetches_when_never_fetched(app, monkeypatch):
    from app.rgl import RglTeamRoster
    from app.rgl_store import ensure_roster
    monkeypatch.setattr("app.rgl.fetch_team_roster", lambda team_id: RglTeamRoster(
        outcome="ok", players=players(("1", "amy", True))))
    with app.test_request_context():
        rows, fetched_at = ensure_roster(101)
    assert [r["name"] for r in rows] == ["amy"]
    assert fetched_at is not None


def test_ensure_roster_skips_fetch_when_fresh(app, monkeypatch):
    from app.rgl_store import ensure_roster, save_roster

    def _fail(team_id):
        raise AssertionError("must not refetch a fresh roster")

    monkeypatch.setattr("app.rgl.fetch_team_roster", _fail)
    with app.test_request_context():
        save_roster(101, players(("1", "amy", True)))  # stamps now
        rows, _ = ensure_roster(101)
    assert [r["name"] for r in rows] == ["amy"]


def test_ensure_roster_refetches_when_stale(app, monkeypatch):
    from app.db import get_db
    from app.rgl import RglTeamRoster
    from app.rgl_store import ensure_roster, save_roster
    monkeypatch.setattr("app.rgl.fetch_team_roster", lambda team_id: RglTeamRoster(
        outcome="ok", players=players(("2", "new", False))))
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    with app.test_request_context():
        save_roster(101, players(("1", "old", True)))
        get_db().execute("UPDATE rgl_roster_meta SET fetched_at = ? WHERE rgl_team_id = 101",
                         (stale,))
        get_db().commit()
        rows, fetched_at = ensure_roster(101)
    assert [r["name"] for r in rows] == ["new"]
    assert fetched_at > stale


def test_ensure_roster_keeps_cache_on_outage(app, monkeypatch):
    from app.db import get_db
    from app.rgl import RglTeamRoster
    from app.rgl_store import ensure_roster, save_roster
    monkeypatch.setattr("app.rgl.fetch_team_roster",
                        lambda team_id: RglTeamRoster(outcome="unavailable"))
    stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    with app.test_request_context():
        save_roster(101, players(("1", "amy", True)))
        get_db().execute("UPDATE rgl_roster_meta SET fetched_at = ? WHERE rgl_team_id = 101",
                         (stale,))
        get_db().commit()
        rows, fetched_at = ensure_roster(101)
    assert [r["name"] for r in rows] == ["amy"]  # stale-if-error
    assert fetched_at == stale                    # stamp untouched by a failed fetch


def test_ensure_roster_cold_cache_outage_returns_empty_unstamped(app, monkeypatch):
    from app.rgl import RglTeamRoster
    from app.rgl_store import ensure_roster
    monkeypatch.setattr("app.rgl.fetch_team_roster",
                        lambda team_id: RglTeamRoster(outcome="unavailable"))
    with app.test_request_context():
        rows, fetched_at = ensure_roster(101)
    assert rows == [] and fetched_at is None


def test_ensure_roster_no_team_returns_empty_unstamped(app, monkeypatch):
    from app.rgl import RglTeamRoster
    from app.rgl_store import ensure_roster
    monkeypatch.setattr("app.rgl.fetch_team_roster",
                        lambda team_id: RglTeamRoster(outcome="no_team"))
    with app.test_request_context():
        rows, fetched_at = ensure_roster(9990001)  # e.g. seeded demo team ids
    assert rows == [] and fetched_at is None
