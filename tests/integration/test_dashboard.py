"""Integration tests for the combined scrims dashboard (feature 004,
contracts/dashboard-routes.md): open listings + my-scrims on one page, query-time
expiry, own-team flagging, empty state, and the /scrims/listings redirect."""
import re
from datetime import datetime, timedelta, timezone

from tests.conftest import rgl_team

A = "76561198000000001"  # team 101, sixes
B = "76561198000000002"  # team 202, sixes
C = "76561198000000003"  # team 303, highlander

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")
TEAM_C = rgl_team(303, "Charlie", "CHA", "highlander")


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def future_form(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")


def post_listing(client, team=101, days=3):
    return client.post("/scrims/listings/new", data={
        "team_id": str(team), "scheduled_at": future_form(days)})


def backdate_all_listings(app, days=1):
    when = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    with app.test_request_context():
        from app.db import get_db
        get_db().execute("UPDATE scrims SET scheduled_at = %s WHERE origin = 'listing'", (when,))
        get_db().commit()


def test_combined_page_shows_listings_and_my_scrims(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    as_user(client, A)
    post_listing(client)                       # Alpha's open listing
    client.post("/scrims/propose", data={      # Alpha proposes to Bravo
        "proposer_team_id": "101", "opponent_team_id": "202",
        "scheduled_at": future_form()})

    as_user(client, B)
    body = client.get("/scrims").get_data(as_text=True)
    assert "Open listings" in body            # listings section present
    assert "Alpha" in body                    # Alpha's listing visible to Bravo
    assert "Incoming proposals" in body       # my-scrims summary on the same page
    assert "Claim" in body                    # eligible claim control inline


def test_all_dashboard_times_are_localizable(app, client, link_team):
    """Listings table, rail items and summaries share one format: readable UTC
    text wrapped in a <time> the shell script localizes (FR-002/FR-007)."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    as_user(client, A)
    post_listing(client)                       # open listing in the main column
    client.post("/scrims/propose", data={      # proposal in the side rail
        "proposer_team_id": "101", "opponent_team_id": "202",
        "scheduled_at": future_form()})

    as_user(client, B)
    body = client.get("/scrims").get_data(as_text=True)
    # every timestamp is a <time class="ts"> the browser can rewrite...
    stamps = re.findall(r'<time class="ts" datetime="([^"]+)">([^<]+)</time>', body)
    assert len(stamps) >= 2  # Alpha's listing row + the incoming proposal rail item
    # ...and each one's fallback text is human-readable UTC, never a raw ISO string
    for iso, text in stamps:
        assert "+00:00" in iso
        assert re.fullmatch(r"[A-Z][a-z]{2} \d{2} \d{1,2}:\d{2} [AP]M UTC", text), text
    assert "time.ts" in body  # the localizing script ships with the page


def test_listings_ordered_soonest_first(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(C, [TEAM_C], persona="CaptainC")
    as_user(client, C)
    post_listing(client, team=303, days=5)     # Charlie, later
    as_user(client, A)
    post_listing(client, team=101, days=2)     # Alpha, sooner

    as_user(client, A)
    body = client.get("/scrims").get_data(as_text=True)
    assert body.index("Alpha") < body.index("Charlie")


def test_own_listing_flagged_and_not_claimable(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    as_user(client, A)
    post_listing(client)
    body = client.get("/scrims").get_data(as_text=True)
    assert "Your listing" in body
    assert "Claim" not in body  # own listing offers no claim control


def test_past_listing_in_neither_section(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    as_user(client, A)
    post_listing(client)
    backdate_all_listings(app)

    as_user(client, B)  # gone from the open-listings section
    assert "Alpha" not in client.get("/scrims").get_data(as_text=True)

    as_user(client, A)  # gone from the owner's my-listings section too
    body = client.get("/scrims").get_data(as_text=True)
    assert "Your listing" not in body and "Cancel listing" not in body
    assert "No open listings" in body


def test_expired_claim_told_no_longer_available(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    as_user(client, A)
    post_listing(client)
    with app.test_request_context():
        from app.db import get_db
        scrim_id = get_db().execute("SELECT id FROM scrims").fetchone()["id"]
    backdate_all_listings(app)

    as_user(client, B)
    resp = client.post(f"/scrims/listings/{scrim_id}/claim", data={"team_id": "202"},
                       follow_redirects=True)
    assert "no longer available" in resp.get_data(as_text=True).lower()
    with app.test_request_context():
        from app.scrims import get_scrim
        row = get_scrim(scrim_id)
        assert row["status"] == "open" and row["opponent_team_id"] is None


def test_empty_state_invites_posting(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    as_user(client, A)
    body = client.get("/scrims").get_data(as_text=True)
    assert "No open listings" in body


def test_format_filter_on_dashboard(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(C, [TEAM_C], persona="CaptainC")
    as_user(client, A)
    post_listing(client, team=101)
    as_user(client, C)
    post_listing(client, team=303)

    body = client.get("/scrims?format=highlander").get_data(as_text=True)
    assert "Charlie" in body and "Alpha" not in body


def test_listings_url_redirects_to_dashboard(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    as_user(client, A)
    resp = client.get("/scrims/listings")
    assert resp.status_code == 302
    assert resp.headers["Location"].rstrip("/").endswith("/scrims")
    resp = client.get("/scrims/listings?format=sixes")
    assert resp.status_code == 302
    assert "format=sixes" in resp.headers["Location"]


def test_dashboard_gates_unchanged(client, login):
    resp = client.get("/scrims")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    login(A)  # signed in, never linked
    resp = client.get("/scrims")
    assert resp.status_code == 302 and resp.headers["Location"].endswith("/account")
