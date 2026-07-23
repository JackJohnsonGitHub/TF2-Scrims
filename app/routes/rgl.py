"""Account area: RGL link status + link/refresh/unlink actions.

The RGL profile is always fetched for the *session's* SteamID (FR-002) — no RGL
id or URL is ever accepted from the form. An `unavailable` outcome leaves any
previously stored link untouched (FR-006 / SC-008).
"""
from flask import Blueprint, flash, redirect, render_template, url_for

from .. import rgl
from ..rgl_store import get_link, get_user_teams, save_link, unlink
from ..security import current_user, login_required

bp = Blueprint("rgl", __name__)

FORMAT_LABELS = {"sixes": "Sixes", "highlander": "Highlander", "prolander": "Prolander"}


@bp.get("/account")
@login_required
def account():
    steam_id = current_user()["steam_id"]
    teams = get_user_teams(steam_id)
    teams_by_format = {}
    for team in teams:
        teams_by_format.setdefault(team["format"], []).append(team)
    return render_template(
        "account.html",
        link=get_link(steam_id),
        teams_by_format=teams_by_format,
        format_labels=FORMAT_LABELS,
    )


def _fetch_and_store(steam_id: str) -> None:
    """Shared by link + refresh: fetch by session SteamID, store the outcome."""
    profile = rgl.fetch_profile(steam_id)
    if profile.outcome == "unavailable":
        flash("RGL is unavailable right now — please try again in a moment.", "error")
        return
    state = save_link(steam_id, profile)
    if state == "linked":
        flash("RGL account linked.", "success")
    elif state == "no_team":
        flash("RGL account linked — no current team found.", "info")
    else:
        flash("No RGL profile was found for your Steam account.", "info")


@bp.post("/rgl/link")
@login_required
def link():
    _fetch_and_store(current_user()["steam_id"])
    return redirect(url_for("rgl.account"))


@bp.post("/rgl/refresh")
@login_required
def refresh():
    _fetch_and_store(current_user()["steam_id"])
    return redirect(url_for("rgl.account"))


@bp.post("/rgl/unlink")
@login_required
def unlink_account():
    unlink(current_user()["steam_id"])
    flash("RGL account unlinked.", "success")
    return redirect(url_for("rgl.account"))
