"""Account area: RGL link status, link/refresh/unlink, and the Steam trade link.

The RGL profile is always fetched for the *session's* SteamID (FR-002) — no RGL
id or URL is ever accepted from the form. An `unavailable` outcome leaves any
previously stored link untouched (FR-006 / SC-008).

The Steam trade link lives here too (feature 005). This blueprint owns `GET /account`
and the template it renders, and its `rgl.account` endpoint is referenced from six
places including the main nav — renaming that to purify a blueprint boundary would be
churn for nothing.
"""
from flask import (Blueprint, flash, redirect, render_template, request, url_for)

from .. import payments, rgl
from ..payments import PaymentError
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
        trade_link=payments.get_trade_link(steam_id),
        trade_error=request.args.get("trade_error"),
    )


@bp.post("/account/trade-link")
@login_required
def save_trade_link():
    """Record the viewer's own Steam trade URL.

    Not cosmetic: the token inside that URL is what `GetTradeHoldDurations` needs, so
    without it we cannot tell whether a trade from this user would sit in escrow for
    15 days — and therefore cannot responsibly let them pay.
    """
    steam_id = current_user()["steam_id"]
    try:
        payments.save_trade_link(steam_id, request.form.get("trade_url", ""))
    except PaymentError as exc:
        return redirect(url_for("rgl.account", trade_error=str(exc)))
    flash("Trade link saved.", "info")
    return redirect(url_for("rgl.account"))


@bp.post("/account/trade-link/delete")
@login_required
def delete_trade_link():
    payments.delete_trade_link(current_user()["steam_id"])
    flash("Trade link removed.", "info")
    return redirect(url_for("rgl.account"))


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
