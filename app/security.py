"""Session-backed identity helpers and the owner-only route guard."""
from functools import wraps
from urllib.parse import urlparse

from flask import g, redirect, request, session, url_for

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
