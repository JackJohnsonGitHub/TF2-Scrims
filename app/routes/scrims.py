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
                      create_listing, create_proposal, decline, get_scrim,
                      get_scrim_for_viewer, incoming_pending, my_open_listings,
                      open_listings, outgoing_pending, upcoming_confirmed,
                      utc_now, withdraw)
from ..security import (current_user, login_required, rgl_link_required,
                        safe_next)
from .. import credits
from .. import servers_store as srv
from ..credits import InsufficientCredits
# Same decoration the Servers page uses, so a server reads identically wherever it is
# shown rather than growing a second formatting path here.
from .servers import _view as srv_view

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


def _wants_server() -> bool:
    return bool(request.form.get("use_credits"))


def _attach_server(scrim_id: int) -> None:
    """Best-effort server attach after a scrim already exists.

    Deliberately never raises. The scrim is created first and unconditionally, and a
    failed reservation leaves it standing with no server — a valid, honest state
    (FR-055). Scheduling is free and must never be blocked, delayed or rolled back by
    anything to do with payment (Principle I, FR-054, SC-014).
    """
    if not _wants_server():
        return
    row = get_scrim(scrim_id)
    if row is None:
        return
    scrim = dict(row)   # sqlite3.Row has no .get()
    try:
        srv.attach_to_scrim(_steam_id(), scrim)
        flash("A server will be ready when the scrim starts. 1 credit reserved.",
              "success")
    except InsufficientCredits as exc:
        flash(f"Scrim scheduled, but no server attached — {exc}", "info")
    except Exception:
        # Never let a server problem look like a scheduling problem.
        flash("Scrim scheduled, but the server could not be attached.", "info")


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
    is_own = scrim["proposer_team_id"] in my_team_ids
    is_opponent = scrim["opponent_team_id"] in my_team_ids
    claim_teams = [] if is_own else [
        t for t in my_teams if t["format"] == scrim["format"]]

    # Which lifecycle actions this viewer may take, mirroring the service rules in
    # scrims.py exactly. A scrim has to be actionable from its own page — the
    # dashboards are a convenience, not the only way to reach a scrim.
    can_respond = scrim["status"] == "pending" and is_opponent
    can_withdraw = scrim["status"] == "pending" and is_own
    can_cancel = scrim["status"] == "confirmed" and (is_own or is_opponent)
    can_cancel_listing = (scrim["origin"] == "listing"
                          and scrim["status"] == "open" and is_own)

    # Attendance renders only for posting-team members (FR-016); the roster
    # section becomes the tracker for them.
    attendance = None
    if is_own:
        attendance = roster_with_attendance(scrim)

    # The scrim's own server, if it has one, plus whether this viewer can act on it.
    # A scrim must be actionable from its own page — including buying it more time
    # mid-match, which is when nobody wants to go hunting for the Servers page.
    server = srv.server_for_scrim(scrim_id)
    balance = credits.available_credits(steam_id)
    can_attach = (server is None and (is_own or is_opponent)
                  and scrim["status"] in ("pending", "confirmed", "open")
                  and scrim["scheduled_at"] > utc_now() and balance >= 1)
    return render_template(
        "scrim_detail.html",
        scrim=scrim,
        server=srv_view(server) if server else None,
        balance=balance,
        can_attach=can_attach,
        can_extend_server=(server is not None
                           and srv.can_manage(server, steam_id)
                           and srv.is_live(server) and balance >= 1),
        extension_minutes=current_app.config["EXTENSION_MINUTES"],
        roster=roster,
        roster_fetched_at=roster_fetched_at,
        claim_teams=claim_teams if open_and_future else [],
        open_and_future=open_and_future,
        is_own=is_own,
        can_respond=can_respond,
        can_withdraw=can_withdraw,
        can_cancel=can_cancel,
        can_cancel_listing=can_cancel_listing,
        attendance=attendance,
        attending=attending_count(attendance) if attendance is not None else 0,
        required=required_players(scrim["format"]),
        can_mark_all=(steam_id == scrim["created_by"]),
        attendance_locked=is_locked(scrim),
        status_labels=STATUS_LABELS,
        format_labels=FORMAT_LABELS,
    )


def _credit_context() -> dict:
    """Whether to offer the spend-a-credit option at all (FR-065), and the price to
    show beside it. An action the balance cannot cover is not rendered."""
    balance = credits.available_credits(_steam_id())
    return {"balance": balance, "can_use_credits": balance >= 1,
            "credit_minutes": current_app.config["CREDIT_MINUTES"]}


def _propose_form_context():
    """Quick pick = on-platform teams only (research §9); the division browser is
    the path to the rest of the league."""
    my_teams = get_user_teams(_steam_id())
    my_ids = {t["rgl_team_id"] for t in my_teams}
    my_formats = {t["format"] for t in my_teams}
    opponents = [t for t in platform_teams()
                 if t["rgl_team_id"] not in my_ids and t["format"] in my_formats]
    return {"my_teams": my_teams, "opponents": opponents,
            "format_labels": FORMAT_LABELS, "browse": None,
            **_credit_context()}


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
        scrim_id = create_proposal(
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
    _attach_server(scrim_id)
    return redirect(url_for("scrims.index"))


@bp.post("/scrims/<int:scrim_id>/server/attach")
@login_required
@rgl_link_required
def attach_server(scrim_id):
    """Attach a server to an already-scheduled scrim.

    The second path to a server: the first is ticking the option while scheduling. Both
    converge here so a team that scheduled before it had credits is not stuck.
    """
    steam_id = _steam_id()
    row = get_scrim_for_viewer(scrim_id, steam_id)
    if row is None:
        abort(404)
    scrim = dict(row)
    if srv.server_for_scrim(scrim_id) is not None:
        flash("That scrim already has a server.", "info")
        return _back("scrims.detail", scrim_id=scrim_id)
    if srv.owning_team_for(steam_id, scrim) is None:
        abort(403)
    try:
        srv.attach_to_scrim(steam_id, scrim)
    except InsufficientCredits as exc:
        flash(str(exc), "error")
        return redirect(url_for("credits.index"))
    flash("A server will be ready when the scrim starts. 1 credit reserved.", "success")
    return _back("scrims.detail", scrim_id=scrim_id)


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
        **_credit_context(),
    )


@bp.post("/scrims/listings/new")
@login_required
@rgl_link_required
def new_listing():
    try:
        scrim_id = create_listing(
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
    _attach_server(scrim_id)
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
    _attach_server(scrim_id)
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
