"""Integration tests for the RGL link flow (contracts/rgl-routes.md) — RGL mocked."""
from tests.conftest import rgl_team


def _link_state(app, steam_id):
    with app.test_request_context():
        from app.rgl_store import get_link
        row = get_link(steam_id)
        return row["state"] if row else None


def test_link_with_teams_shows_them_by_format(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(name="b4nny", verified=True,
             teams=[rgl_team(101, "froyotech", "FRG", "sixes", "RGL-Invite"),
                    rgl_team(202, "Highlander Heroes", "HLH", "highlander")])
    resp = client.post("/rgl/link")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account")

    assert _link_state(app, steam_id) == "linked"
    with app.test_request_context():
        from app.rgl_store import get_team, get_user_teams, is_member
        assert {t["rgl_team_id"] for t in get_user_teams(steam_id)} == {101, 202}
        assert get_team(101)["format"] == "sixes"
        assert is_member(steam_id, 101)

    page = client.get("/account")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "b4nny" in body
    assert "froyotech" in body and "Highlander Heroes" in body
    assert "Sixes" in body and "Highlander" in body
    assert "Verified" in body


def test_link_profile_without_teams_is_no_team(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(name="teamless", teams=[])
    client.post("/rgl/link")
    assert _link_state(app, steam_id) == "no_team"
    body = client.get("/account").get_data(as_text=True)
    assert "no current team" in body.lower()


def test_link_404_is_no_profile_with_friendly_message(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(outcome="no_profile")
    client.post("/rgl/link")
    assert _link_state(app, steam_id) == "no_profile"
    with app.test_request_context():
        from app.rgl_store import get_user_teams
        assert get_user_teams(steam_id) == []
    body = client.get("/account").get_data(as_text=True)
    assert "no rgl profile" in body.lower()


def test_refresh_timeout_keeps_prior_data(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(name="b4nny", teams=[rgl_team(101, "froyotech", "FRG", "sixes")])
    client.post("/rgl/link")

    mock_rgl(outcome="unavailable")
    resp = client.post("/rgl/refresh", follow_redirects=True)
    assert resp.status_code == 200
    assert "unavailable" in resp.get_data(as_text=True).lower()
    # Prior link and team survive the outage.
    assert _link_state(app, steam_id) == "linked"
    with app.test_request_context():
        from app.rgl_store import get_user_teams
        assert [t["rgl_team_id"] for t in get_user_teams(steam_id)] == [101]


def test_refresh_rebuilds_memberships(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(name="b4nny", teams=[rgl_team(101, "froyotech", "FRG", "sixes")])
    client.post("/rgl/link")
    # The user left team 101 and joined 303.
    mock_rgl(name="b4nny", teams=[rgl_team(303, "New Squad", "NEW", "sixes")])
    client.post("/rgl/refresh")
    with app.test_request_context():
        from app.rgl_store import get_user_teams
        assert [t["rgl_team_id"] for t in get_user_teams(steam_id)] == [303]


def test_unlink_removes_link_and_memberships(app, client, login, mock_rgl):
    steam_id = login()
    mock_rgl(name="b4nny", teams=[rgl_team(101, "froyotech", "FRG", "sixes")])
    client.post("/rgl/link")
    client.post("/rgl/unlink")
    assert _link_state(app, steam_id) is None
    with app.test_request_context():
        from app.rgl_store import get_team, get_user_teams
        assert get_user_teams(steam_id) == []
        # Shared team row is kept (other members / scrims may reference it).
        assert get_team(101) is not None
    body = client.get("/account").get_data(as_text=True)
    assert "not linked" in body.lower()


def test_anonymous_rgl_routes_redirect_to_login(client):
    for method, path in [("GET", "/account"), ("POST", "/rgl/link"),
                         ("POST", "/rgl/refresh"), ("POST", "/rgl/unlink")]:
        resp = client.open(path, method=method)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
