"""Scrim scheduling routes (contracts/scrim-routes.md).

All routes are login- and RGL-link-gated (FR-008). The acting team is always
re-validated against the user's own memberships inside `app/scrims.py` — a posted
team id is never trusted (FR-016). Authority failures render as 403; validation
failures re-render with 400 or flash-and-redirect.
"""
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from ..rgl_store import all_teams, get_user_teams
from ..scrims import (ScrimError, accept, cancel, cancel_listing, claim,
                      create_listing, create_proposal, decline,
                      incoming_pending, my_open_listings, open_listings,
                      outgoing_pending, upcoming_confirmed, withdraw)
from ..security import current_user, login_required, rgl_link_required

bp = Blueprint("scrims", __name__)

FORMAT_LABELS = {"sixes": "Sixes", "highlander": "Highlander", "prolander": "Prolander"}


def _steam_id() -> str:
    return current_user()["steam_id"]


def _form_datetime_utc() -> str:
    """Convert the form's datetime-local value (+ optional JS tz offset, minutes
    to add to reach UTC) into an ISO-8601 UTC timestamp."""
    raw = request.form.get("scheduled_at", "")
    try:
        when = datetime.strptime(raw, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise ScrimError("Invalid date/time.")
    try:
        offset = int(request.form.get("tz_offset") or 0)
    except ValueError:
        offset = 0
    return (when + timedelta(minutes=offset)).replace(tzinfo=timezone.utc).isoformat(
        timespec="seconds")


def _int_field(name: str) -> int:
    try:
        return int(request.form.get(name, ""))
    except ValueError:
        raise ScrimError("Invalid team selection.")


def _run_action(action, *args):
    """Shared handler for the POST action endpoints: authority failures are 403,
    everything else flashes and returns to the scrims dashboard."""
    try:
        action(_steam_id(), *args)
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
    return redirect(url_for("scrims.index"))


@bp.get("/scrims")
@login_required
@rgl_link_required
def index():
    steam_id = _steam_id()
    return render_template(
        "scrims.html",
        incoming=incoming_pending(steam_id),
        outgoing=outgoing_pending(steam_id),
        upcoming=upcoming_confirmed(steam_id),
        my_listings=my_open_listings(steam_id),
        my_teams=get_user_teams(steam_id),
        format_labels=FORMAT_LABELS,
    )


def _propose_form_context():
    my_teams = get_user_teams(_steam_id())
    my_ids = {t["rgl_team_id"] for t in my_teams}
    my_formats = {t["format"] for t in my_teams}
    opponents = [t for t in all_teams()
                 if t["rgl_team_id"] not in my_ids and t["format"] in my_formats]
    return {"my_teams": my_teams, "opponents": opponents, "format_labels": FORMAT_LABELS}


@bp.get("/scrims/new")
@login_required
@rgl_link_required
def new():
    return render_template("scrim_new.html", **_propose_form_context())


@bp.post("/scrims/propose")
@login_required
@rgl_link_required
def propose():
    try:
        create_proposal(
            _steam_id(),
            _int_field("proposer_team_id"),
            _int_field("opponent_team_id"),
            _form_datetime_utc(),
            (request.form.get("notes") or "").strip() or None,
        )
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
        return render_template("scrim_new.html", **_propose_form_context()), err.status
    flash("Scrim proposed — waiting for the opponent to accept.", "success")
    return redirect(url_for("scrims.index"))


@bp.post("/scrims/<int:scrim_id>/accept")
@login_required
@rgl_link_required
def accept_scrim(scrim_id):
    return _run_action(accept, scrim_id)


@bp.post("/scrims/<int:scrim_id>/decline")
@login_required
@rgl_link_required
def decline_scrim(scrim_id):
    return _run_action(decline, scrim_id)


@bp.post("/scrims/<int:scrim_id>/withdraw")
@login_required
@rgl_link_required
def withdraw_scrim(scrim_id):
    return _run_action(withdraw, scrim_id)


@bp.post("/scrims/<int:scrim_id>/cancel")
@login_required
@rgl_link_required
def cancel_scrim(scrim_id):
    return _run_action(cancel, scrim_id)


# --- Open listings (US3) ---

@bp.get("/scrims/listings")
@login_required
@rgl_link_required
def listings():
    fmt = request.args.get("format") or None
    my_teams = get_user_teams(_steam_id())
    return render_template(
        "listings.html",
        listings=open_listings(fmt),
        selected_format=fmt,
        my_teams=my_teams,
        my_team_ids={t["rgl_team_id"] for t in my_teams},
        format_labels=FORMAT_LABELS,
    )


@bp.post("/scrims/listings/new")
@login_required
@rgl_link_required
def new_listing():
    try:
        create_listing(
            _steam_id(),
            _int_field("team_id"),
            _form_datetime_utc(),
            (request.form.get("notes") or "").strip() or None,
        )
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
        return redirect(url_for("scrims.listings"))
    flash("Open listing posted — any same-format team can claim it.", "success")
    return redirect(url_for("scrims.index"))


@bp.post("/scrims/listings/<int:scrim_id>/claim")
@login_required
@rgl_link_required
def claim_listing(scrim_id):
    try:
        claim(_steam_id(), scrim_id, _int_field("team_id"))
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
        return redirect(url_for("scrims.listings"))
    flash("Scrim confirmed!", "success")
    return redirect(url_for("scrims.index"))


@bp.post("/scrims/listings/<int:scrim_id>/cancel")
@login_required
@rgl_link_required
def cancel_listing_route(scrim_id):
    return _run_action(cancel_listing, scrim_id)
