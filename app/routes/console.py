"""Admin console command handler.

RCON is the most privileged surface there is, so only the captain the server was
granted to may reach it (constitution IV/VIII) — a teammate can see and join a server
without being able to run commands against it.

`[sim]`: no real RCON traffic occurs this increment. What is real is the refusal: a
server that is not running says so with a reason, rather than answering as though the
command went somewhere.
"""
from flask import Blueprint, abort, render_template, request

from .. import servers_store as store
from ..rgl_store import get_user_teams
from ..security import current_user, login_required

bp = Blueprint("console", __name__)


@bp.post("/servers/<int:server_id>/console")
@login_required
def run_command(server_id):
    steam_id = current_user()["steam_id"]
    team_ids = [t["rgl_team_id"] for t in get_user_teams(steam_id)]
    server = store.get_accessible_server(server_id, steam_id, team_ids)
    if server is None or not store.is_owner(server, steam_id):
        abort(404)

    command = (request.form.get("command") or "").strip()
    console_output = []
    if not store.is_live(server):
        # Refusing beats a placeholder reply that implies the command landed.
        console_output.append({
            "kind": "response",
            "text": f"Not sent — this server is {store.state_label(server).lower()}. "
                    "Commands can only be run while it is running.",
        })
    elif command:
        console_output.append({"kind": "command", "text": command})
        console_output.append(
            {"kind": "response", "text": "Placeholder response — RCON is not wired up yet."}
        )
    from .servers import detail_context
    return render_template(
        "server_detail.html",
        **detail_context(server, steam_id, console_output=console_output))
