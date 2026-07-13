"""Admin console command handler (FR-005).

Echoes the submitted command into the console output with a placeholder response.
No real RCON traffic occurs this phase.
"""
from flask import Blueprint, abort, render_template, request

from ..models import get_server
from ..security import login_required

bp = Blueprint("console", __name__)


@bp.post("/servers/<server_id>/console")
@login_required
def run_command(server_id):
    server = get_server(server_id)
    if server is None:
        abort(404)
    command = (request.form.get("command") or "").strip()
    console_output = []
    if command:
        console_output.append({"kind": "command", "text": command})
        console_output.append(
            {"kind": "response", "text": "Placeholder response — RCON is not wired up yet."}
        )
    return render_template(
        "server_detail.html", server=server, errors={}, console_output=console_output
    )
