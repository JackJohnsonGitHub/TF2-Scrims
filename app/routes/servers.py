"""The Servers page: inventory, detail, and owner settings (feature 005).

Servers are persisted rows resolved through `app/servers_store.py`. There is no
create-a-server route: under constitution Principle VIII a server exists only because
credits were granted, so a self-service creation form would promise an action nobody
can complete. `/servers/new` was removed with feature 005.

Every resolution goes through `_server_or_404` — an inaccessible server must be
indistinguishable from a nonexistent one, so it 404s rather than 403s.
"""
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)

from flask import current_app

from .. import credits
from .. import servers_store as store
from ..credits import InsufficientCredits
from ..models import validate_server_settings
from ..rgl_store import get_user_teams
from ..security import current_user, login_required, safe_next

bp = Blueprint("servers", __name__)


def _viewer():
    """(steam_id, rgl team ids) for the signed-in user — the pair every server
    access check is made against."""
    steam_id = current_user()["steam_id"]
    return steam_id, [t["rgl_team_id"] for t in get_user_teams(steam_id)]


def _server_or_404(server_id):
    """A server the viewer may access, else 404 — an inaccessible server must not
    be distinguishable from a nonexistent one."""
    server = store.get_accessible_server(server_id, *_viewer())
    if server is None:
        abort(404)
    return server


def _view(server: dict) -> dict:
    """Decorate a server row with everything a template needs, so no formatting
    logic ends up duplicated in Jinja."""
    return {
        **server,
        "state_label": store.state_label(server),
        "is_live": store.is_live(server),
        "slots_display": store.slots_display(server),
        "minutes_remaining": store.minutes_remaining(server),
        "grace_remaining": store.grace_minutes_remaining(server),
        "explanation": store.stopped_explanation(server),
        "is_per_scrim": store.is_per_scrim(server),
    }


@bp.get("/servers")
@login_required
def list_servers():
    steam_id, team_ids = _viewer()
    servers = [_view(s) for s in store.accessible_servers(steam_id, team_ids)]
    balance = credits.available_credits(steam_id)
    return render_template(
        "servers_list.html",
        servers=servers,
        linked=bool(team_ids),
        balance=balance,
        # FR-065: an action the balance cannot cover is not rendered at all, and the
        # route to buying credits appears in its place.
        can_extend=balance >= 1,
        price=_price(),
    )


def _price() -> dict:
    from .. import payments
    return payments.price_summary()


def detail_context(server: dict, steam_id: str, *, errors=None,
                   console_output=None) -> dict:
    """The full template context for the detail screen.

    One builder, used by the GET, the settings-validation 400, and the console POST.
    Three call sites assembling this by hand is how one of them ends up missing
    `balance` and blowing up on `balance < 1` against an Undefined.
    """
    balance = credits.available_credits(steam_id)
    return {
        "server": _view(server),
        "is_owner": store.is_owner(server, steam_id),
        "balance": balance,
        "can_extend": balance >= 1,
        "price": _price(),
        "errors": errors or {},
        "console_output": console_output or [],
    }


@bp.get("/servers/<int:server_id>")
@login_required
def server_detail(server_id):
    steam_id, _team_ids = _viewer()
    server = _server_or_404(server_id)
    return render_template("server_detail.html",
                           **detail_context(server, steam_id))


@bp.post("/servers/<int:server_id>/extend")
@login_required
def extend(server_id):
    """Buy more time on a running server.

    Does no network I/O on purpose. This is the mid-match path — twelve people are
    waiting — so it is a local ledger write and a timestamp bump, nothing else.
    """
    steam_id, _team_ids = _viewer()
    server = _server_or_404(server_id)
    if not store.is_owner(server, steam_id):
        abort(404)
    if server["state"] not in (store.RUNNING, store.IN_GRACE):
        flash("That server is not running, so there is no time to extend.", "info")
        return redirect(_back(server_id))

    minutes = current_app.config["EXTENSION_MINUTES"]
    try:
        # Re-checked server-side even though the button is hidden without a balance —
        # an un-rendered action is not a security control.
        credits.spend_extension(
            steam_id, f"+{minutes} min on {server['name']}", server_id=server_id)
    except InsufficientCredits as exc:
        flash(str(exc), "error")
        return redirect(url_for("credits.index"))

    store.extend_window(server_id, minutes)
    if server["state"] == store.IN_GRACE:
        # Back to running: the window now ends in the future, and nobody playing
        # noticed a thing.
        store.set_state(server_id, store.RUNNING)
    flash(f"Added {minutes} minutes.", "info")
    return redirect(_back(server_id))


def _back(server_id):
    return (safe_next(request.form.get("next"))
            or url_for("servers.server_detail", server_id=server_id))


@bp.post("/servers/<int:server_id>/settings")
@login_required
def update_settings(server_id):
    steam_id, _team_ids = _viewer()
    server = _server_or_404(server_id)
    # Settings belong to the captain the server was granted to. A teammate can see and
    # join it but not reconfigure it (Principle VIII: individual ownership).
    if not store.is_owner(server, steam_id):
        abort(404)

    form = request.form
    # FR-028: a per-scrim server exists for one hour of one match, so renaming and
    # resizing it are noise. Its name and slot count are fixed and not accepted from
    # the form — a posted value for either is ignored rather than trusted.
    per_scrim = store.is_per_scrim(server)
    name = server["name"] if per_scrim else form.get("name", "")
    max_slots = str(server["max_slots"]) if per_scrim else form.get("max_slots", "")
    errors = validate_server_settings(
        name, form.get("map", ""), max_slots, form.get("join_password", ""))
    if errors:
        return render_template(
            "server_detail.html",
            **detail_context(server, steam_id, errors=errors)), 400

    store.update_settings(
        server_id,
        name=name.strip(),
        map_name=form["map"].strip(),
        max_slots=int(max_slots),
        join_password=(form.get("join_password") or "").strip() or None,
    )
    flash("Settings saved.", "info")
    return redirect(safe_next(request.form.get("next"))
                    or url_for("servers.server_detail", server_id=server_id))
