"""Integration tests for the listing detail page: roster display + fallbacks,
visibility rules, claim-from-detail (feature 004, contracts/dashboard-routes.md)."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import rgl_team

A = "76561198000000001"  # team 101, sixes (listing owner in most tests)
B = "76561198000000002"  # team 202, sixes (eligible claimer)
C = "76561198000000003"  # team 303, highlander (unrelated linked user)

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")
TEAM_C = rgl_team(303, "Charlie", "CHA", "highlander")


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def future_form(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


@pytest.fixture
def mock_roster(monkeypatch):
    """Patch the roster client (rgl_store calls it via the module, same seam as
    fetch_profile). Returns a setter so tests can swap outcomes."""
    def _mock(outcome="ok", players=()):
        from app.rgl import RglRosterPlayer, RglTeamRoster
        roster = RglTeamRoster(
            outcome=outcome,
            players=[RglRosterPlayer(steam_id=s, name=n, is_leader=lead)
                     for s, n, lead in players])
        monkeypatch.setattr("app.rgl.fetch_team_roster", lambda team_id: roster)
    return _mock


@pytest.fixture
def three_users(link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    link_team(C, [TEAM_C], persona="CaptainC")


def post_listing(client, owner=A, team=101, days=3):
    as_user(client, owner)
    client.post("/scrims/listings/new", data={
        "team_id": str(team), "scheduled_at": future_form(days)})


def listing_id(app):
    with app.test_request_context():
        from app.db import get_db
        return get_db().execute(
            "SELECT id FROM scrims ORDER BY id DESC").fetchone()["id"]


def backdate(app, scrim_id, days=1):
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with app.test_request_context():
        from app.db import get_db
        get_db().execute("UPDATE scrims SET scheduled_at = ? WHERE id = ?", (when, scrim_id))
        get_db().commit()


ROSTER = (("76561198059104274", "crazedorangutan", True),
          ("76561199088088348", "TheLazySquid", False))


def test_detail_shows_listing_and_roster_with_leader_badge(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    scrim_id = listing_id(app)

    as_user(client, B)
    body = client.get(f"/scrims/{scrim_id}").get_data(as_text=True)
    assert "Alpha" in body and "Sixes" in body
    assert "crazedorangutan" in body and "TheLazySquid" in body
    assert "Leader" in body


def test_fresh_cache_is_not_refetched(app, client, three_users, monkeypatch):
    from app.rgl import RglRosterPlayer
    with app.test_request_context():
        from app.rgl_store import save_roster
        save_roster(101, [RglRosterPlayer("1", "cachedplayer", True)])

    def _fail(team_id):
        raise AssertionError("fresh roster must not be refetched")
    monkeypatch.setattr("app.rgl.fetch_team_roster", _fail)

    post_listing(client)
    as_user(client, B)
    body = client.get(f"/scrims/{listing_id(app)}").get_data(as_text=True)
    assert "cachedplayer" in body


def test_outage_with_warm_cache_serves_cached_roster(app, client, three_users, mock_roster):
    from app.rgl import RglRosterPlayer
    stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(timespec="seconds")
    with app.test_request_context():
        from app.db import get_db
        from app.rgl_store import save_roster
        save_roster(101, [RglRosterPlayer("1", "cachedplayer", False)])
        get_db().execute("UPDATE rgl_roster_meta SET fetched_at = ?", (stale,))
        get_db().commit()
    mock_roster(outcome="unavailable")

    post_listing(client)
    as_user(client, B)
    body = client.get(f"/scrims/{listing_id(app)}").get_data(as_text=True)
    assert "cachedplayer" in body  # stale-if-error


def test_outage_with_cold_cache_shows_friendly_notice(app, client, three_users, mock_roster):
    mock_roster(outcome="unavailable")
    post_listing(client)
    as_user(client, B)
    body = client.get(f"/scrims/{listing_id(app)}").get_data(as_text=True)
    assert "Roster unavailable" in body
    assert "Alpha" in body  # listing details still render — never an error page


def test_open_listing_visible_to_any_linked_user(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    as_user(client, C)  # different format, unrelated team
    assert client.get(f"/scrims/{listing_id(app)}").status_code == 200


def test_confirmed_scrim_detail_participants_only(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    scrim_id = listing_id(app)
    as_user(client, B)
    client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "202"})

    for user, expected in ((A, 200), (B, 200), (C, 404)):
        as_user(client, user)
        assert client.get(f"/scrims/{scrim_id}").status_code == expected


def test_expired_listing_detail_participants_only(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    scrim_id = listing_id(app)
    backdate(app, scrim_id)

    for user, expected in ((A, 200), (B, 404), (C, 404)):
        as_user(client, user)
        assert client.get(f"/scrims/{scrim_id}").status_code == expected


def test_proposal_detail_participants_only(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    as_user(client, A)
    client.post("/scrims/propose", data={
        "proposer_team_id": "101", "opponent_team_id": "202",
        "scheduled_at": future_form()})
    with app.test_request_context():
        from app.db import get_db
        scrim_id = get_db().execute("SELECT id FROM scrims").fetchone()["id"]

    for user, expected in ((A, 200), (B, 200), (C, 404)):
        as_user(client, user)
        assert client.get(f"/scrims/{scrim_id}").status_code == expected


def test_unknown_scrim_is_404(app, client, three_users):
    as_user(client, A)
    assert client.get("/scrims/9999").status_code == 404


def test_claim_form_shown_to_eligible_and_claims(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    scrim_id = listing_id(app)

    as_user(client, B)
    body = client.get(f"/scrims/{scrim_id}").get_data(as_text=True)
    assert "Claim" in body
    resp = client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "202"})
    assert resp.status_code == 302
    with app.test_request_context():
        from app.scrims import get_scrim
        assert get_scrim(scrim_id)["status"] == "confirmed"


def test_no_claim_form_for_owner_or_wrong_format(app, client, three_users, mock_roster):
    mock_roster(players=ROSTER)
    post_listing(client)
    scrim_id = listing_id(app)

    as_user(client, A)   # owner
    assert "Claim" not in client.get(f"/scrims/{scrim_id}").get_data(as_text=True)
    as_user(client, C)   # no same-format team
    assert "Claim" not in client.get(f"/scrims/{scrim_id}").get_data(as_text=True)


# --- Attendance tracker (US3, FR-013..FR-017) ---

A2 = "76561198000000005"  # teammate on team 101, not the listing creator
TEAM_ROSTER = (("76561198000000001", "CaptainA", True),
               (A2, "MateA2", False),
               ("76561198000000077", "NoAccountNed", False))


@pytest.fixture
def team_listing(app, client, three_users, link_team, mock_roster):
    """A's team 101 posts a listing; A2 is a second (non-creator) member; the
    roster includes an account-less player."""
    link_team(A2, [TEAM_A], persona="MateA2")
    mock_roster(players=TEAM_ROSTER)
    post_listing(client)
    return listing_id(app)


def mark(client, scrim_id, player, status="attending", **extra):
    return client.post(f"/scrims/{scrim_id}/attendance",
                       data={"player_steam_id": player, "status": status, **extra})


def attendance_status(app, scrim_id, player):
    with app.test_request_context():
        from app.db import get_db
        row = get_db().execute(
            "SELECT status FROM scrim_attendance WHERE scrim_id=? AND player_steam_id=?",
            (scrim_id, player)).fetchone()
        return row["status"] if row else None


def test_tracker_renders_only_for_posting_team(app, client, team_listing):
    for user in (A, A2):
        as_user(client, user)
        assert "Attendance" in client.get(f"/scrims/{team_listing}").get_data(as_text=True)
    for user in (B, C):  # eligible claimer and unrelated user see roster, no tracker
        as_user(client, user)
        body = client.get(f"/scrims/{team_listing}").get_data(as_text=True)
        assert "Attendance" not in body and "NoAccountNed" in body


def test_member_marks_self_and_tally_updates(app, client, team_listing):
    as_user(client, A2)
    resp = mark(client, team_listing, A2)
    assert resp.status_code == 302
    assert attendance_status(app, team_listing, A2) == "attending"
    body = client.get(f"/scrims/{team_listing}").get_data(as_text=True)
    assert "1 / 6" in body  # sixes needs 6


def test_member_cannot_mark_teammate(app, client, team_listing):
    as_user(client, A2)
    resp = mark(client, team_listing, "76561198000000077")
    assert resp.status_code == 403
    assert attendance_status(app, team_listing, "76561198000000077") is None


def test_creator_marks_accountless_player(app, client, team_listing):
    as_user(client, A)
    resp = mark(client, team_listing, "76561198000000077")
    assert resp.status_code == 302
    assert attendance_status(app, team_listing, "76561198000000077") == "attending"


def test_outsiders_cannot_mark(app, client, team_listing):
    for user in (B, C):
        as_user(client, user)
        assert mark(client, team_listing, user).status_code == 403


def test_tracker_survives_claim_until_scrim_time(app, client, team_listing):
    as_user(client, B)
    client.post(f"/scrims/listings/{team_listing}/claim", data={"team_id": "202"})

    as_user(client, A)
    body = client.get(f"/scrims/{team_listing}").get_data(as_text=True)
    assert "Attendance" in body  # still there after confirm (FR-017)
    assert mark(client, team_listing, A2).status_code == 302

    backdate(app, team_listing)
    mark(client, team_listing, A2, status="not_attending")
    # write rejected once scheduled time has passed; status unchanged
    assert attendance_status(app, team_listing, A2) == "attending"
    body = client.get(f"/scrims/{team_listing}").get_data(as_text=True)
    assert "read-only" in body.lower()


def test_attendance_markup_never_leaks_to_other_teams(app, client, team_listing):
    as_user(client, A)
    mark(client, team_listing, A2)
    as_user(client, B)
    body = client.get(f"/scrims/{team_listing}").get_data(as_text=True)
    assert "attending" not in body.lower()  # no statuses, no tally for outsiders
