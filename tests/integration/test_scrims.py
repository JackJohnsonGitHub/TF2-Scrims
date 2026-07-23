"""Integration tests for scrim scheduling routes (contracts/scrim-routes.md)."""
from datetime import datetime, timedelta, timezone

from tests.conftest import rgl_team

A = "76561198000000001"  # team 101, sixes
B = "76561198000000002"  # team 202, sixes
C = "76561198000000003"  # team 303, highlander

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")
TEAM_C = rgl_team(303, "Charlie", "CHA", "highlander")


def future_form(days=3):
    """A datetime-local form value in the future (treated as UTC without offset)."""
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def setup_two_sixes_teams(link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")


def propose(client, when=None, opponent=202, team=101):
    return client.post("/scrims/propose", data={
        "proposer_team_id": str(team),
        "opponent_team_id": str(opponent),
        "scheduled_at": when or future_form(),
    })


def only_scrim_id(app):
    with app.test_request_context():
        from app.db import get_db
        rows = get_db().execute("SELECT id FROM scrims").fetchall()
        assert len(rows) == 1
        return rows[0]["id"]


def scrim_status(app, scrim_id):
    with app.test_request_context():
        from app.scrims import get_scrim
        return get_scrim(scrim_id)["status"]


def test_propose_accept_roundtrip(app, client, link_team):
    setup_two_sixes_teams(link_team)

    as_user(client, A)
    resp = propose(client)
    assert resp.status_code == 302
    scrim_id = only_scrim_id(app)
    assert scrim_status(app, scrim_id) == "pending"
    body = client.get("/scrims").get_data(as_text=True)
    assert "Bravo" in body  # outgoing proposal names the opponent

    as_user(client, B)
    body = client.get("/scrims").get_data(as_text=True)
    assert "Alpha" in body  # incoming proposal names the proposer
    resp = client.post(f"/scrims/{scrim_id}/accept")
    assert resp.status_code == 302
    assert scrim_status(app, scrim_id) == "confirmed"

    # Upcoming for both sides.
    for user in (A, B):
        as_user(client, user)
        body = client.get("/scrims").get_data(as_text=True)
        assert "Alpha" in body and "Bravo" in body


def test_decline_closes_without_match(app, client, link_team):
    setup_two_sixes_teams(link_team)
    as_user(client, A)
    propose(client)
    scrim_id = only_scrim_id(app)
    as_user(client, B)
    client.post(f"/scrims/{scrim_id}/decline")
    assert scrim_status(app, scrim_id) == "declined"


def test_withdraw_pending_proposal(app, client, link_team):
    setup_two_sixes_teams(link_team)
    as_user(client, A)
    propose(client)
    scrim_id = only_scrim_id(app)
    client.post(f"/scrims/{scrim_id}/withdraw")
    assert scrim_status(app, scrim_id) == "cancelled"


def test_non_member_accept_is_403(app, client, link_team):
    setup_two_sixes_teams(link_team)
    link_team(C, [TEAM_C], persona="CaptainC")
    as_user(client, A)
    propose(client)
    scrim_id = only_scrim_id(app)
    as_user(client, C)
    resp = client.post(f"/scrims/{scrim_id}/accept")
    assert resp.status_code == 403
    assert scrim_status(app, scrim_id) == "pending"


def test_invalid_proposals_are_400(app, client, link_team):
    setup_two_sixes_teams(link_team)
    link_team(C, [TEAM_C], persona="CaptainC")
    as_user(client, A)

    cross_format = propose(client, opponent=303)
    own_team = propose(client, opponent=101)
    past = propose(client, when=(datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M"))
    for resp in (cross_format, own_team, past):
        assert resp.status_code == 400
    with app.test_request_context():
        from app.db import get_db
        assert get_db().execute("SELECT COUNT(*) c FROM scrims").fetchone()["c"] == 0


def test_cancel_confirmed_by_either_team(app, client, link_team):
    setup_two_sixes_teams(link_team)
    as_user(client, A)
    propose(client)
    scrim_id = only_scrim_id(app)
    as_user(client, B)
    client.post(f"/scrims/{scrim_id}/accept")
    as_user(client, A)
    client.post(f"/scrims/{scrim_id}/cancel")
    assert scrim_status(app, scrim_id) == "cancelled"  # kept, not deleted


def test_unlinked_user_is_redirected_to_account(app, client, login):
    login(A)  # signed in but never RGL-linked
    resp = client.get("/scrims")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/account")
    resp = client.get("/scrims", follow_redirects=True)
    assert "link your rgl account" in resp.get_data(as_text=True).lower()


def test_anonymous_scrims_routes_redirect_to_login(client):
    resp = client.get("/scrims")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_no_scheduling_action_provisions_servers(app, client, link_team):
    from app.models import all_servers
    baseline = [s.id for s in all_servers()]
    setup_two_sixes_teams(link_team)
    as_user(client, A)
    propose(client)
    scrim_id = only_scrim_id(app)
    as_user(client, B)
    client.post(f"/scrims/{scrim_id}/accept")
    client.post(f"/scrims/{scrim_id}/cancel")
    assert [s.id for s in all_servers()] == baseline  # FR-018: no side effects


# --- Open listings (US3) ---

def post_listing(client, team=101, when=None):
    return client.post("/scrims/listings/new", data={
        "team_id": str(team),
        "scheduled_at": when or future_form(),
    })


def test_listing_post_claim_roundtrip(app, client, link_team):
    setup_two_sixes_teams(link_team)

    as_user(client, A)
    resp = post_listing(client)
    assert resp.status_code == 302
    scrim_id = only_scrim_id(app)
    assert scrim_status(app, scrim_id) == "open"
    # Owner sees it under "my open listings" on the dashboard.
    assert "Alpha" in client.get("/scrims").get_data(as_text=True)

    as_user(client, B)
    body = client.get("/scrims/listings").get_data(as_text=True)
    assert "Alpha" in body
    resp = client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "202"})
    assert resp.status_code == 302
    assert scrim_status(app, scrim_id) == "confirmed"

    # Confirmed for both; gone from the open list.
    for user in (A, B):
        as_user(client, user)
        assert "Bravo" in client.get("/scrims").get_data(as_text=True)
    assert "Alpha" not in client.get("/scrims/listings").get_data(as_text=True)


def test_listings_filter_by_format(app, client, link_team):
    setup_two_sixes_teams(link_team)
    link_team(C, [TEAM_C], persona="CaptainC")
    as_user(client, A)
    post_listing(client, team=101)
    as_user(client, C)
    post_listing(client, team=303)

    as_user(client, B)
    body = client.get("/scrims/listings?format=highlander").get_data(as_text=True)
    assert "Charlie" in body and "Alpha" not in body


def test_second_claim_told_no_longer_available(app, client, link_team):
    setup_two_sixes_teams(link_team)
    link_team("76561198000000004", [rgl_team(404, "Delta", "DLT", "sixes")], persona="CaptainD")
    as_user(client, A)
    post_listing(client)
    scrim_id = only_scrim_id(app)

    as_user(client, B)
    client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "202"})
    as_user(client, "76561198000000004")
    resp = client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "404"},
                       follow_redirects=True)
    assert "no longer available" in resp.get_data(as_text=True).lower()

    with app.test_request_context():
        from app.db import get_db
        confirmed = get_db().execute(
            "SELECT COUNT(*) c FROM scrims WHERE status='confirmed'").fetchone()["c"]
        assert confirmed == 1
    with app.test_request_context():
        from app.scrims import get_scrim
        assert get_scrim(scrim_id)["opponent_team_id"] == 202


def test_owner_cancels_unclaimed_listing(app, client, link_team):
    setup_two_sixes_teams(link_team)
    as_user(client, A)
    post_listing(client)
    scrim_id = only_scrim_id(app)
    client.post(f"/scrims/listings/{scrim_id}/cancel")
    assert scrim_status(app, scrim_id) == "cancelled"
    as_user(client, B)
    assert "Alpha" not in client.get("/scrims/listings").get_data(as_text=True)


def test_unlinked_or_anonymous_listings_redirected(app, client, login):
    resp = client.get("/scrims/listings")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    login(A)  # signed in, not linked
    resp = client.get("/scrims/listings")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/account")
