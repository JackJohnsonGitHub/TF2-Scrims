"""Server list, create, detail, and settings screens (FR-002..FR-004, FR-006, FR-007).

All actions are placeholders this phase: forms validate and give feedback but nothing
is created or persisted.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from ..models import all_servers, get_server, validate_server_settings
from ..security import login_required

bp = Blueprint("servers", __name__)


@bp.get("/servers")
@login_required
def list_servers():
    return render_template("servers_list.html", servers=all_servers())


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
    server = get_server(server_id)
    if server is None:
        abort(404)
    return render_template("server_detail.html", server=server, errors={}, console_output=[])


@bp.post("/servers/<server_id>/settings")
@login_required
def update_settings(server_id):
    server = get_server(server_id)
    if server is None:
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
            "server_detail.html", server=server, errors=errors, console_output=[]
        ), 400
    # Placeholder: settings are not persisted or applied this phase (FR-006).
    flash("Placeholder — settings are not saved yet.", "info")
    return redirect(url_for("servers.server_detail", server_id=server_id))
