"""Home screen: public landing when anonymous, dashboard when signed in (FR-008)."""
from flask import Blueprint, render_template

from ..models import all_servers
from ..security import current_user

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    if current_user() is None:
        return render_template("landing.html")
    servers = all_servers()
    online = sum(1 for s in servers if s.is_online)
    return render_template(
        "dashboard.html",
        servers=servers,
        total=len(servers),
        online=online,
    )
