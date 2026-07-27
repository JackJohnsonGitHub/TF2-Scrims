"""Server list, create, detail, and settings screens (FR-002..FR-004, FR-006, FR-007).

All actions are placeholders this phase: forms validate and give feedback but nothing
is created or persisted.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..models import (accessible_servers, get_accessible_server,
                      validate_server_settings)
from ..rgl_store import get_user_teams
from ..security import current_user, login_required

bp = Blueprint("servers", __name__)


def _viewer():
    """(steam_id, rgl team ids) for the signed-in user — the pair every server
    access check is made against."""
    steam_id = current_user()["steam_id"]
    return steam_id, [t["rgl_team_id"] for t in get_user_teams(steam_id)]


def _server_or_404(server_id):
    """A server the viewer may access, else 404 — an inaccessible server must not
    be distinguishable from a nonexistent one."""
    server = get_accessible_server(server_id, *_viewer())
    if server is None:
        abort(404)
    return server


@bp.get("/servers")
@login_required
def list_servers():
    return render_template("servers_list.html", servers=accessible_servers(*_viewer()))


@bp.route("/servers/new", methods=["GET", "POST"])
@login_required
def new_server():
    if request.method == "POST":
        form = request.form
        errors = validate_server_settings(
            form.get("name", ""),
            form.get("map", ""),
            form.get("max_slots", ""),
            form.get("join_password", ""),
        )
        if errors:
            return render_template("server_new.html", errors=errors, form=form), 400
        # Placeholder: not wired up yet — nothing is created this phase (FR-006).
        flash("Placeholder — server creation is not wired up yet.", "info")
        return redirect(url_for("servers.list_servers"))
    return render_template("server_new.html", errors={}, form={})


@bp.get("/servers/<server_id>")
@login_required
def server_detail(server_id):
    server = _server_or_404(server_id)
    return render_template("server_detail.html", server=server, errors={}, console_output=[])


@bp.post("/servers/<server_id>/settings")
@login_required
def update_settings(server_id):
    server = _server_or_404(server_id)
    form = request.form
    errors = validate_server_settings(
        form.get("name", ""),
        form.get("map", ""),
        form.get("max_slots", ""),
        form.get("join_password", ""),
    )
    if errors:
        return render_template(
            "server_detail.html", server=server, errors=errors, console_output=[]
        ), 400
    # Placeholder: settings are not persisted or applied this phase (FR-006).
    flash("Placeholder — settings are not saved yet.", "info")
    return redirect(url_for("servers.server_detail", server_id=server_id))
