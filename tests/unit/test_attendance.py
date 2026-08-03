"""Unit tests for the attendance tracker rules (app/attendance.py):
self-or-creator writes, listing-origin only, frozen after scrim time, tally
(feature 004, data-model.md invariants)."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import rgl_team

A = "76561198000000001"   # creator, member of team 101 (sixes)
A2 = "76561198000000005"  # teammate on 101, not the listing creator
B = "76561198000000002"   # member of team 202 (sixes)
P3 = "76561198000000077"  # roster player with no app account

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")


def future(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def past(days=1):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def roster_players():
    from app.rgl import RglRosterPlayer
    return [RglRosterPlayer(A, "CaptainA", True),
            RglRosterPlayer(A2, "MateA2", False),
            RglRosterPlayer(P3, "NoAccountNed", False)]


@pytest.fixture
def ctx(app, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(A2, [TEAM_A], persona="MateA2")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.rgl_store import save_roster
        save_roster(101, roster_players())
        yield


@pytest.fixture
def listing(ctx):
    from app.scrims import create_listing
    return create_listing(A, 101, future())


def get_row(scrim_id, player):
    from app.db import get_db
    return get_db().execute(
        "SELECT * FROM scrim_attendance WHERE scrim_id = %s AND player_steam_id = %s",
        (scrim_id, player)).fetchone()


def backdate(scrim_id):
    from app.db import get_db
    get_db().execute("UPDATE scrims SET scheduled_at = %s WHERE id = %s",
                     (past(), scrim_id))
    get_db().commit()


# --- Authorization matrix (FR-014) ---

def test_member_sets_own_status(listing):
    from app.attendance import set_status
    set_status(A2, listing, A2, "not_attending")
    row = get_row(listing, A2)
    assert row["status"] == "not_attending" and row["marked_by"] == A2


def test_member_cannot_set_teammates_status(listing):
    from app.attendance import set_status
    from app.scrims import ScrimForbidden
    with pytest.raises(ScrimForbidden):
        set_status(A2, listing, P3, "attending")


def test_creator_sets_anyones_status(listing):
    from app.attendance import set_status
    set_status(A, listing, P3, "attending")
    row = get_row(listing, P3)
    assert row["status"] == "attending"
    assert row["player_name"] == "NoAccountNed"  # snapshotted from the roster cache
    assert row["marked_by"] == A


def test_non_team_member_forbidden(listing):
    from app.attendance import set_status
    from app.scrims import ScrimForbidden
    with pytest.raises(ScrimForbidden):
        set_status(B, listing, B, "attending")   # B is not on the posting team


# --- Validity rules ---

def test_invalid_status_rejected(listing):
    from app.attendance import set_status
    from app.scrims import ScrimError
    with pytest.raises(ScrimError, match="status"):
        set_status(A, listing, A, "maybe")


def test_unknown_scrim_rejected(ctx):
    from app.attendance import set_status
    from app.scrims import ScrimError
    with pytest.raises(ScrimError):
        set_status(A, 9999, A, "attending")


def test_proposal_origin_rejected(ctx):
    from app.attendance import set_status
    from app.scrims import ScrimError, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    with pytest.raises(ScrimError, match="listing"):
        set_status(A, scrim_id, A, "attending")


def test_cancelled_listing_rejected(listing):
    from app.attendance import set_status
    from app.scrims import ScrimError, cancel_listing
    cancel_listing(A, listing)
    with pytest.raises(ScrimError):
        set_status(A, listing, A, "attending")


def test_past_scrim_time_is_read_only(listing):
    from app.attendance import set_status
    from app.scrims import ScrimError
    backdate(listing)
    with pytest.raises(ScrimError, match="passed"):
        set_status(A, listing, A, "attending")
    assert get_row(listing, A) is None


def test_claimed_listing_still_editable_until_scrim_time(listing):
    from app.attendance import set_status
    from app.scrims import claim
    claim(B, listing, 202)  # confirmed now
    set_status(A, listing, P3, "attending")
    assert get_row(listing, P3)["status"] == "attending"


def test_upsert_updates_single_row(listing):
    from app.attendance import set_status
    set_status(A, listing, P3, "attending")
    set_status(A, listing, P3, "unconfirmed")
    from app.db import get_db
    rows = get_db().execute(
        "SELECT * FROM scrim_attendance WHERE scrim_id = %s", (listing,)).fetchall()
    assert len(rows) == 1 and rows[0]["status"] == "unconfirmed"


# --- Merged view + tally (FR-013 / FR-015, departed flag) ---

def test_roster_merges_statuses_with_unconfirmed_default(listing):
    from app.attendance import roster_with_attendance, set_status
    from app.scrims import get_scrim
    set_status(A, listing, P3, "attending")
    entries = roster_with_attendance(get_scrim(listing))
    by_id = {e["steam_id"]: e for e in entries}
    assert by_id[P3]["status"] == "attending"
    assert by_id[A]["status"] == "unconfirmed"
    assert by_id[A2]["status"] == "unconfirmed"
    assert not any(e["departed"] for e in entries)


def test_departed_player_kept_and_flagged(listing):
    from app.attendance import roster_with_attendance, set_status
    from app.rgl_store import save_roster
    from app.scrims import get_scrim
    set_status(A, listing, P3, "attending")
    save_roster(101, roster_players()[:2])  # NoAccountNed left the team
    entries = roster_with_attendance(get_scrim(listing))
    ned = next(e for e in entries if e["steam_id"] == P3)
    assert ned["departed"] and ned["name"] == "NoAccountNed"
    assert ned["status"] == "attending"


def test_attending_count_and_required_players(listing):
    from app.attendance import (attending_count, required_players,
                                roster_with_attendance, set_status)
    from app.scrims import get_scrim
    set_status(A, listing, A, "attending")
    set_status(A, listing, A2, "attending")
    set_status(A, listing, P3, "not_attending")
    entries = roster_with_attendance(get_scrim(listing))
    assert attending_count(entries) == 2
    assert required_players("sixes") == 6
    assert required_players("prolander") == 7
    assert required_players("highlander") == 9
