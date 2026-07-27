"""Scrim scheduling routes (contracts/scrim-routes.md).

All routes are login- and RGL-link-gated (FR-008). The acting team is always
re-validated against the user's own memberships inside `app/scrims.py` — a posted
team id is never trusted (FR-016). Authority failures render as 403; validation
failures re-render with 400 or flash-and-redirect.
"""
from datetime import datetime, timedelta, timezone

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, url_for)

from ..attendance import (STATUS_LABELS, attending_count, is_locked,
                          required_players, roster_with_attendance, set_status)
from ..rgl_store import (division_browser, ensure_roster, ensure_season,
                         get_team, get_user_teams, hydrate_season_teams,
                         platform_teams, season_progress, team_on_platform)
from ..scrims import (ScrimError, accept, cancel, cancel_listing, claim,
                      create_listing, create_proposal, decline,
                      get_scrim_for_viewer, incoming_pending, my_open_listings,
                      open_listings, outgoing_pending, upcoming_confirmed,
                      utc_now, withdraw)
from ..security import (current_user, login_required, rgl_link_required,
                        safe_next)

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


def _back(default: str = "scrims.index", **kwargs):
    """Return to the page the action was taken from — the home dashboard and the
    scrims dashboard both carry these forms, and being bounced to /scrims from
    elsewhere loses your place. `safe_next` rejects off-site targets, so a forged
    `next` cannot turn an action into an open redirect."""
    return redirect(safe_next(request.form.get("next")) or url_for(default, **kwargs))


def _run_action(action, *args):
    """Shared handler for the POST action endpoints: authority failures are 403,
    everything else flashes and returns to where the user acted."""
    try:
        action(_steam_id(), *args)
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
    return _back()


@bp.get("/scrims")
@login_required
@rgl_link_required
def index():
    """The combined scrims dashboard (004 FR-001..FR-007): all-format open future
    listings plus the viewer's my-scrims summary, on one page."""
    steam_id = _steam_id()
    fmt = request.args.get("format") or None
    my_teams = get_user_teams(steam_id)
    return render_template(
        "scrims.html",
        listings=open_listings(fmt),
        selected_format=fmt,
        my_team_ids={t["rgl_team_id"] for t in my_teams},
        incoming=incoming_pending(steam_id),
        outgoing=outgoing_pending(steam_id),
        upcoming=upcoming_confirmed(steam_id),
        my_listings=my_open_listings(steam_id),
        my_teams=my_teams,
        format_labels=FORMAT_LABELS,
    )


@bp.get("/scrims/<int:scrim_id>")
@login_required
@rgl_link_required
def detail(scrim_id):
    """Listing detail (004 FR-009..FR-012): scrim info + the posting team's cached
    RGL roster; claim form when the viewer is eligible. Visibility per research §6."""
    steam_id = _steam_id()
    scrim = get_scrim_for_viewer(scrim_id, steam_id)
    if scrim is None:
        abort(404)

    roster, roster_fetched_at = ensure_roster(scrim["proposer_team_id"])
    my_teams = get_user_teams(steam_id)
    my_team_ids = {t["rgl_team_id"] for t in my_teams}
    open_and_future = (scrim["status"] == "open"
                       and scrim["scheduled_at"] > utc_now())
    claim_teams = [] if scrim["proposer_team_id"] in my_team_ids else [
        t for t in my_teams if t["format"] == scrim["format"]]

    # Attendance renders only for posting-team members (FR-016); the roster
    # section becomes the tracker for them.
    attendance = None
    if scrim["proposer_team_id"] in my_team_ids:
        attendance = roster_with_attendance(scrim)
    return render_template(
        "scrim_detail.html",
        scrim=scrim,
        roster=roster,
        roster_fetched_at=roster_fetched_at,
        claim_teams=claim_teams if open_and_future else [],
        open_and_future=open_and_future,
        is_own=scrim["proposer_team_id"] in my_team_ids,
        attendance=attendance,
        attending=attending_count(attendance) if attendance is not None else 0,
        required=required_players(scrim["format"]),
        can_mark_all=(steam_id == scrim["created_by"]),
        attendance_locked=is_locked(scrim),
        status_labels=STATUS_LABELS,
        format_labels=FORMAT_LABELS,
    )


def _propose_form_context():
    """Quick pick = on-platform teams only (research §9); the division browser is
    the path to the rest of the league."""
    my_teams = get_user_teams(_steam_id())
    my_ids = {t["rgl_team_id"] for t in my_teams}
    my_formats = {t["format"] for t in my_teams}
    opponents = [t for t in platform_teams()
                 if t["rgl_team_id"] not in my_ids and t["format"] in my_formats]
    return {"my_teams": my_teams, "opponents": opponents,
            "format_labels": FORMAT_LABELS, "browse": None}


def _division_browser_context(my_teams):
    """US4 (contracts/propose-discovery-routes.md): season directory for the
    selected proposing team — ensure the season, hydrate one bounded batch, and
    expose divisions / a division's labeled teams / progress to the template."""
    if not my_teams:
        return None
    team_id = request.args.get("team_id", type=int)
    proposing = next((t for t in my_teams if t["rgl_team_id"] == team_id), my_teams[0])
    division_id = request.args.get("division_id", type=int)
    opponent_id = request.args.get("opponent_id", type=int)

    browse = {
        "proposing": proposing, "season": None, "divisions": [], "teams": [],
        "selected_division": division_id, "hydrated": 0, "total": 0,
        "opponent": None, "rgl_down": False,
        "no_season": proposing["season_id"] is None,
    }
    if browse["no_season"]:
        return browse
    season = ensure_season(proposing["season_id"])
    if season is None:
        browse["rgl_down"] = True
        return browse
    hydrate_season_teams(proposing["season_id"], current_app.config["RGL_HYDRATE_BATCH"])
    browse["season"] = season
    browse["hydrated"], browse["total"] = season_progress(proposing["season_id"])
    browse["divisions"], browse["teams"] = division_browser(
        proposing["season_id"], division_id)

    if opponent_id and opponent_id != proposing["rgl_team_id"]:
        opponent = get_team(opponent_id)
        if opponent is not None and opponent["format"] == proposing["format"]:
            browse["opponent"] = opponent
    return browse


@bp.get("/scrims/new")
@login_required
@rgl_link_required
def new():
    ctx = _propose_form_context()
    browse = _division_browser_context(ctx["my_teams"])
    ctx["browse"] = browse
    if browse and browse["opponent"] is not None:
        # The browsed opponent renders as its own (pre-selected) option.
        ctx["opponents"] = [t for t in ctx["opponents"]
                            if t["rgl_team_id"] != browse["opponent"]["rgl_team_id"]]
    return render_template("scrim_new.html", **ctx)


@bp.post("/scrims/propose")
@login_required
@rgl_link_required
def propose():
    try:
        opponent_team_id = _int_field("opponent_team_id")
        create_proposal(
            _steam_id(),
            _int_field("proposer_team_id"),
            opponent_team_id,
            _form_datetime_utc(),
            (request.form.get("notes") or "").strip() or None,
        )
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
        return render_template("scrim_new.html", **_propose_form_context()), err.status
    if team_on_platform(opponent_team_id):
        flash("Scrim proposed — waiting for the opponent to accept.", "success")
    else:
        flash("Scrim proposed — this team isn't on the platform yet, so they'll "
              "see it once a member joins and links their RGL account.", "success")
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
    """Merged into the dashboard (004): keep old links working via redirect."""
    fmt = request.args.get("format") or None
    return redirect(url_for("scrims.index", format=fmt))


@bp.get("/scrims/listings/new")
@login_required
@rgl_link_required
def new_listing_form():
    """Dedicated post-a-listing page (the form used to live on the dashboard)."""
    return render_template(
        "listing_new.html",
        my_teams=get_user_teams(_steam_id()),
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
        return redirect(url_for("scrims.new_listing_form"))
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
        return _back()
    flash("Scrim confirmed!", "success")
    return _back()


@bp.post("/scrims/listings/<int:scrim_id>/cancel")
@login_required
@rgl_link_required
def cancel_listing_route(scrim_id):
    return _run_action(cancel_listing, scrim_id)


# --- Attendance (004 US3) ---

@bp.post("/scrims/<int:scrim_id>/attendance")
@login_required
@rgl_link_required
def set_attendance(scrim_id):
    """Upsert one player's status (self, or anyone for the listing creator —
    FR-014). Authority failures are 403; validation failures flash on the detail
    page."""
    try:
        set_status(
            _steam_id(), scrim_id,
            request.form.get("player_steam_id", ""),
            request.form.get("status", ""),
            (request.form.get("player_name") or "").strip() or None,
        )
    except ScrimError as err:
        if err.status == 403:
            abort(403)
        flash(str(err), "error")
    return redirect(url_for("scrims.detail", scrim_id=scrim_id))
