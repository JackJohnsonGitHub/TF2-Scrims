"""Session-backed identity helpers and the owner-only route guard."""
from functools import wraps
from urllib.parse import urlparse

from flask import flash, g, redirect, request, session, url_for

from .accounts import get_by_steam_id


def current_user() -> dict | None:
    """Resolve the signed-in Steam id (from the signed session cookie) to its user
    row, or None when anonymous. Cached on `g` for the request."""
    if "current_user" not in g:
        steam_id = session.get("steam_id")
        g.current_user = get_by_steam_id(steam_id) if steam_id else None
    return g.current_user


def safe_next(target: str | None) -> str | None:
    """Return `target` only if it is a local path (no host/scheme) — prevents
    open-redirects through the ?next= parameter (FR-007)."""
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return None
    return target


def login_required(view):
    """Redirect anonymous requests to sign-in, preserving where they were headed."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapped


def rgl_link_required(view):
    """Gate for scheduling actions (FR-008): the user must be RGL-linked with at
    least one current team. Apply under `login_required`."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        from .rgl_store import get_user_teams

        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if not get_user_teams(user["steam_id"]):
            flash("Link your RGL account and be on a team to schedule scrims.", "error")
            return redirect(url_for("rgl.account"))
        return view(*args, **kwargs)

    return wrapped
