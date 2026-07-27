"""Home screen: public landing when anonymous, dashboard when signed in (FR-008).

Scrims lead the signed-in dashboard (constitution v3.0.0, Principle I): scheduling is
the free core loop, so "/" opens on the viewer's matches, the proposals waiting on
them, and listings they could claim. The placeholder server content from feature 001
stays below it — servers are the paid upsell (Principle VIII), just not built yet.

Unlike /scrims this route is deliberately NOT `rgl_link_required`: an unlinked user
must still get a usable page telling them how to start.
"""
from flask import Blueprint, render_template

from ..rgl_store import get_user_teams
from ..scrims import (incoming_pending, my_open_listings, open_listings,
                      upcoming_confirmed)
from ..security import current_user

bp = Blueprint("dashboard", __name__)

FORMAT_LABELS = {"sixes": "Sixes", "highlander": "Highlander", "prolander": "Prolander"}

#: How many of the soonest open listings the home preview shows before deferring to
#: the full scrims dashboard.
LISTING_PREVIEW = 5


@bp.get("/")
def index():
    user = current_user()
    if user is None:
        return render_template("landing.html")

    steam_id = user["steam_id"]
    my_teams = get_user_teams(steam_id)
    my_team_ids = {t["rgl_team_id"] for t in my_teams}

    # The scrim queries only run for a linked user with a team; without one there is
    # nothing to act for, and the page renders the link-your-RGL-account prompt.
    upcoming, incoming, my_listings, listings = [], [], [], []
    if my_teams:
        upcoming = upcoming_confirmed(steam_id)
        incoming = incoming_pending(steam_id)
        my_listings = my_open_listings(steam_id)
        # Soonest first (open_listings orders by scheduled_at); the viewer's own
        # listings get their own section, so they don't crowd out claimable ones.
        listings = [s for s in open_listings()
                    if s["proposer_team_id"] not in my_team_ids][:LISTING_PREVIEW]

    # The home page no longer lists servers — the side box just links to /servers,
    # which does its own access filtering (constitution VIII).
    return render_template(
        "dashboard.html",
        my_teams=my_teams,
        upcoming=upcoming,
        incoming=incoming,
        my_listings=my_listings,
        listings=listings,
        format_labels=FORMAT_LABELS,
    )
