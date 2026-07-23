"""Unit tests for the scrim state machine and validators (app/scrims.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import rgl_team

A = "76561198000000001"  # member of team 101 (sixes)
B = "76561198000000002"  # member of team 202 (sixes)
C = "76561198000000003"  # member of team 303 (highlander)

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")
TEAM_C = rgl_team(303, "Charlie", "CHA", "highlander")


def future(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def past(days=3):
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


@pytest.fixture
def teams(link_team):
    link_team(A, [TEAM_A])
    link_team(B, [TEAM_B])
    link_team(C, [TEAM_C])


@pytest.fixture
def ctx(app, teams):
    with app.test_request_context():
        yield


def get(scrim_id):
    from app.scrims import get_scrim
    return get_scrim(scrim_id)


# --- Directed proposals (US2) ---

def test_create_proposal_is_pending(ctx):
    from app.scrims import create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    row = get(scrim_id)
    assert row["status"] == "pending"
    assert row["origin"] == "proposal"
    assert row["format"] == "sixes"
    assert row["proposer_team_id"] == 101
    assert row["opponent_team_id"] == 202
    assert row["created_by"] == A


def test_accept_confirms(ctx):
    from app.scrims import accept, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    accept(B, scrim_id)
    assert get(scrim_id)["status"] == "confirmed"


def test_decline_closes(ctx):
    from app.scrims import create_proposal, decline
    scrim_id = create_proposal(A, 101, 202, future())
    decline(B, scrim_id)
    assert get(scrim_id)["status"] == "declined"


def test_withdraw_cancels(ctx):
    from app.scrims import create_proposal, withdraw
    scrim_id = create_proposal(A, 101, 202, future())
    withdraw(A, scrim_id)
    assert get(scrim_id)["status"] == "cancelled"


def test_cancel_confirmed_keeps_row(ctx):
    from app.scrims import accept, cancel, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    accept(B, scrim_id)
    cancel(B, scrim_id)
    row = get(scrim_id)
    assert row is not None and row["status"] == "cancelled"


def test_either_team_may_cancel_confirmed(ctx):
    from app.scrims import accept, cancel, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    accept(B, scrim_id)
    cancel(A, scrim_id)
    assert get(scrim_id)["status"] == "cancelled"


# --- Validation rejects ---

def test_cross_format_proposal_rejected(ctx):
    from app.scrims import ScrimError, create_proposal
    with pytest.raises(ScrimError, match="same format"):
        create_proposal(A, 101, 303, future())


def test_self_scrim_rejected(ctx):
    from app.scrims import ScrimError, create_proposal
    with pytest.raises(ScrimError, match="own team"):
        create_proposal(A, 101, 101, future())


def test_past_time_rejected(ctx):
    from app.scrims import ScrimError, create_proposal
    with pytest.raises(ScrimError, match="future"):
        create_proposal(A, 101, 202, past())


def test_invalid_time_rejected(ctx):
    from app.scrims import ScrimError, create_proposal
    with pytest.raises(ScrimError, match="date/time"):
        create_proposal(A, 101, 202, "not-a-time")


# --- Authority (FR-016): membership required for every transition ---

def test_propose_for_team_you_are_not_on_forbidden(ctx):
    from app.scrims import ScrimForbidden, create_proposal
    with pytest.raises(ScrimForbidden):
        create_proposal(B, 101, 202, future())


def test_accept_requires_opponent_membership(ctx):
    from app.scrims import ScrimForbidden, accept, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    with pytest.raises(ScrimForbidden):
        accept(A, scrim_id)  # proposer cannot accept their own proposal
    with pytest.raises(ScrimForbidden):
        accept(C, scrim_id)  # unrelated team cannot accept


def test_withdraw_requires_proposer_membership(ctx):
    from app.scrims import ScrimForbidden, create_proposal, withdraw
    scrim_id = create_proposal(A, 101, 202, future())
    with pytest.raises(ScrimForbidden):
        withdraw(B, scrim_id)


def test_cancel_requires_participant_membership(ctx):
    from app.scrims import ScrimForbidden, accept, cancel, create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    accept(B, scrim_id)
    with pytest.raises(ScrimForbidden):
        cancel(C, scrim_id)


# --- Transition guards / terminal states ---

def test_accept_only_from_pending(ctx):
    from app.scrims import ScrimError, accept, create_proposal, decline
    scrim_id = create_proposal(A, 101, 202, future())
    decline(B, scrim_id)
    with pytest.raises(ScrimError):
        accept(B, scrim_id)
    assert get(scrim_id)["status"] == "declined"  # terminal states are immutable


def test_cancel_only_from_confirmed(ctx):
    from app.scrims import ScrimError, cancel, create_proposal, withdraw
    scrim_id = create_proposal(A, 101, 202, future())
    withdraw(A, scrim_id)
    with pytest.raises(ScrimError):
        cancel(A, scrim_id)


# --- Open listings (US3) ---

def test_create_listing_is_open_without_opponent(ctx):
    from app.scrims import create_listing
    scrim_id = create_listing(A, 101, future())
    row = get(scrim_id)
    assert row["status"] == "open"
    assert row["origin"] == "listing"
    assert row["opponent_team_id"] is None
    assert row["format"] == "sixes"


def test_claim_confirms_and_sets_opponent(ctx):
    from app.scrims import claim, create_listing
    scrim_id = create_listing(A, 101, future())
    claim(B, scrim_id, 202)
    row = get(scrim_id)
    assert row["status"] == "confirmed"
    assert row["opponent_team_id"] == 202


def test_claim_cross_format_rejected(ctx):
    from app.scrims import ScrimError, claim, create_listing
    scrim_id = create_listing(A, 101, future())
    with pytest.raises(ScrimError, match="same format"):
        claim(C, scrim_id, 303)
    assert get(scrim_id)["status"] == "open"


def test_claim_own_listing_rejected(ctx):
    from app.scrims import ScrimError, claim, create_listing
    scrim_id = create_listing(A, 101, future())
    with pytest.raises(ScrimError, match="own listing"):
        claim(A, scrim_id, 101)


def test_claim_requires_membership_of_claiming_team(ctx):
    from app.scrims import ScrimForbidden, claim, create_listing
    scrim_id = create_listing(A, 101, future())
    with pytest.raises(ScrimForbidden):
        claim(C, scrim_id, 202)  # C is not on team 202


def test_second_claim_loses(ctx):
    from app.scrims import ScrimError, claim, create_listing
    from tests.conftest import rgl_team as make_team
    scrim_id = create_listing(A, 101, future())
    claim(B, scrim_id, 202)
    with pytest.raises(ScrimError, match="no longer available"):
        claim(B, scrim_id, 202)
    assert get(scrim_id)["opponent_team_id"] == 202  # first claim stands


def test_listing_past_time_rejected(ctx):
    from app.scrims import ScrimError, create_listing
    with pytest.raises(ScrimError, match="future"):
        create_listing(A, 101, past())


def test_owner_cancels_unclaimed_listing(ctx):
    from app.scrims import cancel_listing, create_listing
    scrim_id = create_listing(A, 101, future())
    cancel_listing(A, scrim_id)
    assert get(scrim_id)["status"] == "cancelled"


def test_cancel_listing_requires_owner_membership(ctx):
    from app.scrims import ScrimForbidden, cancel_listing, create_listing
    scrim_id = create_listing(A, 101, future())
    with pytest.raises(ScrimForbidden):
        cancel_listing(B, scrim_id)


def test_claimed_listing_cannot_be_cancelled_as_listing(ctx):
    from app.scrims import ScrimError, cancel_listing, claim, create_listing
    scrim_id = create_listing(A, 101, future())
    claim(B, scrim_id, 202)
    with pytest.raises(ScrimError):
        cancel_listing(A, scrim_id)


def test_open_listings_filter_by_format(ctx):
    from app.scrims import create_listing, open_listings
    create_listing(A, 101, future())
    create_listing(C, 303, future())
    assert len(open_listings()) == 2
    assert [r["proposer_team_id"] for r in open_listings("sixes")] == [101]
    assert [r["proposer_team_id"] for r in open_listings("highlander")] == [303]


# --- Expiry (feature 004, FR-003): past listings vanish read-side, stay claimless ---

def backdate(scrim_id, when):
    from app.db import get_db
    get_db().execute("UPDATE scrims SET scheduled_at = ? WHERE id = ?", (when, scrim_id))
    get_db().commit()


def test_open_listings_exclude_past(ctx):
    from app.scrims import create_listing, open_listings
    fresh = create_listing(A, 101, future())
    expired = create_listing(C, 303, future())
    backdate(expired, past(days=1))
    assert [r["id"] for r in open_listings()] == [fresh]
    assert open_listings("highlander") == []


def test_my_open_listings_exclude_past(ctx):
    from app.scrims import create_listing, my_open_listings
    scrim_id = create_listing(A, 101, future())
    assert [r["id"] for r in my_open_listings(A)] == [scrim_id]
    backdate(scrim_id, past(days=1))
    assert my_open_listings(A) == []


def test_claim_expired_listing_rejected_and_row_unchanged(ctx):
    from app.scrims import ScrimError, claim, create_listing, get_scrim
    scrim_id = create_listing(A, 101, future())
    backdate(scrim_id, past(days=1))
    with pytest.raises(ScrimError, match="no longer available"):
        claim(B, scrim_id, 202)
    row = get_scrim(scrim_id)
    assert row["status"] == "open" and row["opponent_team_id"] is None


# --- Detail visibility (feature 004, research §6) ---

def viewer(scrim_id, steam_id):
    from app.scrims import get_scrim_for_viewer
    return get_scrim_for_viewer(scrim_id, steam_id)


def test_open_future_listing_visible_to_any_linked_user(ctx):
    from app.scrims import create_listing
    scrim_id = create_listing(A, 101, future())
    assert viewer(scrim_id, C) is not None  # unrelated team, still linked


def test_expired_listing_visible_to_owner_members_only(ctx):
    from app.scrims import create_listing
    scrim_id = create_listing(A, 101, future())
    backdate(scrim_id, past(days=1))
    assert viewer(scrim_id, A) is not None
    assert viewer(scrim_id, B) is None
    assert viewer(scrim_id, C) is None


def test_confirmed_scrim_visible_to_participants_only(ctx):
    from app.scrims import claim, create_listing
    scrim_id = create_listing(A, 101, future())
    claim(B, scrim_id, 202)
    assert viewer(scrim_id, A) is not None
    assert viewer(scrim_id, B) is not None
    assert viewer(scrim_id, C) is None


def test_proposal_visible_to_participants_only(ctx):
    from app.scrims import create_proposal
    scrim_id = create_proposal(A, 101, 202, future())
    assert viewer(scrim_id, A) is not None
    assert viewer(scrim_id, B) is not None
    assert viewer(scrim_id, C) is None


def test_missing_scrim_is_none(ctx):
    assert viewer(9999, A) is None
