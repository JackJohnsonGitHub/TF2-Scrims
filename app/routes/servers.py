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

from .. import servers_store as store
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
    }


@bp.get("/servers")
@login_required
def list_servers():
    steam_id, team_ids = _viewer()
    servers = [_view(s) for s in store.accessible_servers(steam_id, team_ids)]
    return render_template(
        "servers_list.html",
        servers=servers,
        linked=bool(team_ids),
    )


@bp.get("/servers/<int:server_id>")
@login_required
def server_detail(server_id):
    steam_id, _team_ids = _viewer()
    server = _server_or_404(server_id)
    return render_template(
        "server_detail.html",
        server=_view(server),
        is_owner=store.is_owner(server, steam_id),
        errors={},
        console_output=[],
    )


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
    errors = validate_server_settings(
        form.get("name", ""),
        form.get("map", ""),
        form.get("max_slots", ""),
        form.get("join_password", ""),
    )
    if errors:
        return render_template(
            "server_detail.html", server=_view(server), is_owner=True,
            errors=errors, console_output=[]
        ), 400

    store.update_settings(
        server_id,
        name=form["name"].strip(),
        map_name=form["map"].strip(),
        max_slots=int(form["max_slots"]),
        join_password=(form.get("join_password") or "").strip() or None,
    )
    flash("Settings saved.", "info")
    return redirect(safe_next(request.form.get("next"))
                    or url_for("servers.server_detail", server_id=server_id))
