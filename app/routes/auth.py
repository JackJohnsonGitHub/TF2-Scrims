"""Steam sign-in / sign-out routes."""
from flask import (Blueprint, current_app, redirect, render_template, request,
                   session, url_for)

from ..accounts import upsert_on_login
from ..security import safe_next
from ..steam import build_login_url, fetch_summary, verify_return

bp = Blueprint("auth", __name__)


@bp.get("/login")
def login():
    # Preserve where the user was headed (owner-only guard sends ?next=...).
    nxt = safe_next(request.args.get("next"))
    if nxt:
        session["next"] = nxt
    return redirect(build_login_url(current_app.config["BASE_URL"]))


@bp.get("/login/return")
def login_return():
    # Server-side verification is mandatory before any session is established.
    steam_id = verify_return(request.args.to_dict(flat=True))
    if steam_id is None:
        return render_template("login_error.html"), 400

    persona, avatar = fetch_summary(steam_id, current_app.config["STEAM_API_KEY"])
    upsert_on_login(steam_id, persona, avatar)

    # Capture the post-login destination before clearing the session (fresh session
    # on login guards against fixation).
    nxt = safe_next(session.get("next"))
    session.clear()
    session["steam_id"] = steam_id
    session.permanent = True

    return redirect(nxt or url_for("dashboard.index"))


@bp.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect(url_for("dashboard.index"))
