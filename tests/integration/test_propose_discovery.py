"""Integration tests for the division browser in the propose flow (US4,
contracts/propose-discovery-routes.md). RGL season + team-summary clients mocked."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import rgl_team

A = "76561198000000001"  # team 101, sixes, season 140
B = "76561198000000002"  # team 202, sixes, season 140 (on-platform quick-pick entry)
C = "76561198000000003"  # team 303, highlander, season 141

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes", season=140)
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes", season=140)
TEAM_C = rgl_team(303, "Charlie", "CHA", "highlander", season=141)

SIXES_SEASON = {
    "name": "6s Season 20", "format": "sixes",
    "sorting": {"9001": 0, "9002": 1},
    "team_ids": [101, 601, 602],
}
HL_SEASON = {
    "name": "HL Season 15", "format": "highlander",
    "sorting": {"9101": 0},
    "team_ids": [303, 701],
}

TEAM_SUMMARIES = {
    101: ("Alpha", "ALP", 9001, "Invite"),
    601: ("Rivals", "RVL", 9001, "Invite"),
    602: ("Midpack", "MID", 9002, "Main"),
    303: ("Charlie", "CHA", 9101, "HL-Gold"),
    701: ("Nine Lads", "NL", 9101, "HL-Gold"),
}


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def future_form(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
def mock_directory(monkeypatch):
    """Mock fetch_season / fetch_team_summary with per-id canned data; returns the
    list of team-summary fetch calls for call-count assertions."""
    from app.rgl import RglSeason, RglTeamSummary
    calls = []

    def _season(season_id):
        data = {140: SIXES_SEASON, 141: HL_SEASON}.get(season_id)
        if data is None:
            return RglSeason(outcome="no_season")
        return RglSeason(outcome="ok", name=data["name"], format=data["format"],
                         division_sorting=dict(data["sorting"]),
                         team_ids=list(data["team_ids"]))

    def _summary(team_id):
        calls.append(team_id)
        if team_id not in TEAM_SUMMARIES:
            return RglTeamSummary(outcome="no_team")
        name, tag, div_id, div_name = TEAM_SUMMARIES[team_id]
        return RglTeamSummary(outcome="ok", rgl_team_id=team_id, name=name,
                              tag=tag, division_id=div_id, division_name=div_name)

    monkeypatch.setattr("app.rgl.fetch_season", _season)
    monkeypatch.setattr("app.rgl.fetch_team_summary", _summary)
    return calls


@pytest.fixture
def rgl_down(monkeypatch):
    from app.rgl import RglSeason, RglTeamSummary
    monkeypatch.setattr("app.rgl.fetch_season",
                        lambda sid: RglSeason(outcome="unavailable"))
    monkeypatch.setattr("app.rgl.fetch_team_summary",
                        lambda tid: RglTeamSummary(outcome="unavailable"))


@pytest.fixture
def users(link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    link_team(C, [TEAM_C], persona="CaptainC")


def test_division_selector_scoped_to_proposing_teams_format(app, client, users, mock_directory):
    as_user(client, A)
    body = client.get("/scrims/new?team_id=101").get_data(as_text=True)
    assert "Invite" in body and "Main" in body
    assert "HL-Gold" not in body  # never another format's divisions

    as_user(client, C)
    body = client.get("/scrims/new?team_id=303").get_data(as_text=True)
    assert "HL-Gold" in body
    assert "Invite" not in body and "Main" not in body


def test_hydration_is_bounded_with_progress_note(app, client, users, mock_directory):
    app.config["RGL_HYDRATE_BATCH"] = 2
    as_user(client, A)
    body = client.get("/scrims/new?team_id=101").get_data(as_text=True)
    assert len(mock_directory) == 2            # exactly one batch of team fetches
    assert "Loaded 2 of 3 teams" in body
    body = client.get("/scrims/new?team_id=101").get_data(as_text=True)
    assert len(mock_directory) == 3            # second request finishes hydration
    assert "Loaded" not in body                # fully hydrated → no progress note
    client.get("/scrims/new?team_id=101")
    assert len(mock_directory) == 3            # steady state: zero RGL team calls


def test_division_team_list_labels_and_own_team_unselectable(app, client, users, mock_directory):
    as_user(client, A)
    client.get("/scrims/new?team_id=101")      # hydrate (default batch covers all)
    body = client.get("/scrims/new?team_id=101&division_id=9001").get_data(as_text=True)
    assert "Rivals" in body
    assert "not on the platform yet" in body   # off-platform label on Rivals
    assert "opponent_id=601" in body           # Rivals selectable
    assert "opponent_id=101" not in body       # own team never selectable


def test_browsed_opponent_preselected(app, client, users, mock_directory):
    as_user(client, A)
    client.get("/scrims/new?team_id=101")
    body = client.get("/scrims/new?team_id=101&division_id=9001&opponent_id=601"
                      ).get_data(as_text=True)
    assert 'value="601" selected' in body


def test_off_platform_proposal_roundtrip(app, client, users, mock_directory):
    as_user(client, A)
    client.get("/scrims/new?team_id=101")      # hydrate so team 601 exists locally
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": "101", "opponent_team_id": "601",
        "scheduled_at": future_form()})
    assert resp.status_code == 302

    with app.test_request_context():
        from app.db import get_db
        scrim = get_db().execute("SELECT * FROM scrims").fetchone()
        assert scrim["status"] == "pending" and scrim["opponent_team_id"] == 601

    body = client.get("/scrims").get_data(as_text=True)
    assert "Rivals" in body                    # outgoing shows the opponent
    assert "join the platform" in body         # awaiting-them-to-join note

    as_user(client, B)                         # unrelated linked user cannot accept
    assert client.post(f"/scrims/{scrim['id']}/accept").status_code == 403

    as_user(client, A)                         # withdraw works as always
    client.post(f"/scrims/{scrim['id']}/withdraw")
    with app.test_request_context():
        from app.scrims import get_scrim
        assert get_scrim(scrim["id"])["status"] == "cancelled"


def test_on_platform_outgoing_has_no_join_note(app, client, users, mock_directory):
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": "101", "opponent_team_id": "202",
        "scheduled_at": future_form()})
    body = client.get("/scrims").get_data(as_text=True)
    assert "Bravo" in body and "join the platform" not in body


def test_rgl_down_cold_shows_notice_and_quick_pick_works(app, client, users, rgl_down):
    as_user(client, A)
    resp = client.get("/scrims/new?team_id=101")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "couldn't reach RGL" in body
    assert 'name="opponent_team_id"' in body   # quick pick renders
    assert "Bravo" in body                     # on-platform same-format team offered
    resp = client.post("/scrims/propose", data={
        "proposer_team_id": "101", "opponent_team_id": "202",
        "scheduled_at": future_form()})
    assert resp.status_code == 302             # form still works via quick pick


def test_rgl_down_warm_directory_still_browsable(app, client, users, mock_directory, monkeypatch):
    as_user(client, A)
    client.get("/scrims/new?team_id=101")      # build + hydrate directory
    from app.rgl import RglSeason, RglTeamSummary
    monkeypatch.setattr("app.rgl.fetch_season",
                        lambda sid: RglSeason(outcome="unavailable"))
    monkeypatch.setattr("app.rgl.fetch_team_summary",
                        lambda tid: RglTeamSummary(outcome="unavailable"))
    body = client.get("/scrims/new?team_id=101&division_id=9001").get_data(as_text=True)
    assert "Rivals" in body                    # stale directory still served


def test_quick_pick_never_lists_off_platform_teams(app, client, users, mock_directory):
    as_user(client, A)
    client.get("/scrims/new?team_id=101")      # full hydration → Rivals in rgl_teams
    body = client.get("/scrims/new?team_id=101").get_data(as_text=True)
    assert '<option value="202"' in body       # Bravo (on-platform) in quick pick
    assert '<option value="601"' not in body   # Rivals only in the browser, never the dropdown


def test_team_without_season_degrades_gracefully(app, client, link_team, mock_directory):
    no_season = rgl_team(505, "Legacy", "LGC", "sixes", season=None)
    link_team("76561198000000009", [no_season], persona="OldCaptain")
    as_user(client, "76561198000000009")
    resp = client.get("/scrims/new?team_id=505")
    assert resp.status_code == 200
    assert "no season information" in resp.get_data(as_text=True).lower()