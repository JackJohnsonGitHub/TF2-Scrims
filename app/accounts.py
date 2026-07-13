"""User-account data access.

`steam_id` is only ever written from a server-side-verified Steam identity — never
from client input (see the auth flow and Constitution Principle IV).
"""
from datetime import datetime, timezone

from .db import get_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_on_login(steam_id: str, persona_name: str, avatar_url: str | None) -> dict:
    """Create the account on first sign-in, or refresh persona/avatar/last_login on
    a returning sign-in. Never creates a duplicate for the same steam_id (SC-006)."""
    db = get_db()
    now = _now()
    existing = get_by_steam_id(steam_id)
    if existing is None:
        db.execute(
            "INSERT INTO users (steam_id, persona_name, avatar_url, created_at, last_login_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (steam_id, persona_name, avatar_url, now, now),
        )
    else:
        db.execute(
            "UPDATE users SET persona_name = ?, avatar_url = ?, last_login_at = ?"
            " WHERE steam_id = ?",
            (persona_name, avatar_url, now, steam_id),
        )
    db.commit()
    return get_by_steam_id(steam_id)


def get_by_steam_id(steam_id: str) -> dict | None:
    row = get_db().execute(
        "SELECT steam_id, persona_name, avatar_url, created_at, last_login_at"
        " FROM users WHERE steam_id = ?",
        (steam_id,),
    ).fetchone()
    return dict(row) if row is not None else None
