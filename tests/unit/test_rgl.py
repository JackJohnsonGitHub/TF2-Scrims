"""Unit tests for the RGL public API client (app/rgl.py) — HTTP mocked."""
import requests

from app import rgl


class FakeResponse:
    def __init__(self, status_code=200, payload=None, bad_json=False):
        self.status_code = status_code
        self._payload = payload
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise ValueError("not json")
        return self._payload


PROFILE_PAYLOAD = {
    "name": "b4nny",
    "status": {"isVerified": True, "isBanned": False, "isOnProbation": False},
    "currentTeams": {
        "sixes": {
            "id": 101, "tag": "FRG", "name": "froyotech",
            "seasonId": 140, "divisionName": "RGL-Invite",
        },
        "highlander": {
            "id": 202, "tag": "HL", "name": "Highlander Heroes",
            "seasonId": 141, "divisionName": "RGL-Amateur",
        },
        "prolander": None,
    },
}


def test_parses_profile_and_teams_per_format(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=PROFILE_PAYLOAD))
    with app.app_context():
        profile = rgl.fetch_profile("76561198000000001")
    assert profile.outcome == "ok"
    assert profile.name == "b4nny"
    assert profile.is_verified and not profile.is_banned and not profile.is_on_probation
    assert [(t.rgl_team_id, t.format) for t in profile.teams] == [(101, "sixes"), (202, "highlander")]
    sixes = profile.teams[0]
    assert sixes.name == "froyotech"
    assert sixes.tag == "FRG"
    assert sixes.division_name == "RGL-Invite"
    assert sixes.season_id == 140


def test_all_null_current_teams_is_ok_with_no_teams(app, monkeypatch):
    payload = {"name": "teamless", "status": {}, "currentTeams":
               {"sixes": None, "highlander": None, "prolander": None}}
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload=payload))
    with app.app_context():
        profile = rgl.fetch_profile("76561198000000002")
    assert profile.outcome == "ok"
    assert profile.teams == []


def test_404_maps_to_no_profile(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=404))
    with app.app_context():
        assert rgl.fetch_profile("1").outcome == "no_profile"


def test_empty_payload_maps_to_no_profile(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(payload={}))
    with app.app_context():
        assert rgl.fetch_profile("1").outcome == "no_profile"


def test_timeout_maps_to_unavailable(app, monkeypatch):
    def _raise(url, timeout):
        raise requests.Timeout("slow")
    monkeypatch.setattr(rgl.requests, "get", _raise)
    with app.app_context():
        assert rgl.fetch_profile("1").outcome == "unavailable"


def test_5xx_maps_to_unavailable(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(status_code=502))
    with app.app_context():
        assert rgl.fetch_profile("1").outcome == "unavailable"


def test_invalid_json_maps_to_unavailable(app, monkeypatch):
    monkeypatch.setattr(rgl.requests, "get",
                        lambda url, timeout: FakeResponse(bad_json=True))
    with app.app_context():
        assert rgl.fetch_profile("1").outcome == "unavailable"
