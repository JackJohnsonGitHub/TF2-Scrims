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
    a returning sign-in. Never creates a duplicate for the same steam_id (SC-006).

    One statement, not a read-then-write. Two simultaneous first sign-ins for the same
    account — two app copies, or a double-clicked login — both saw `existing is None` and
    both inserted, and the loser surfaced a unique violation as an error page on somebody's
    very first visit. SQLite's serialized writer made that nearly unreachable; running more
    than one copy of the app (FR-014) makes it reachable, so it is closed here rather than
    left to timing (research R19).

    `created_at` is deliberately not in the UPDATE clause: a returning sign-in refreshes
    the persona, the avatar, and the last login, and must never rewrite when the account
    was created.
    """
    db = get_db()
    now = _now()
    db.execute(
        """INSERT INTO users (steam_id, persona_name, avatar_url, created_at, last_login_at)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (steam_id) DO UPDATE SET
               persona_name  = excluded.persona_name,
               avatar_url    = excluded.avatar_url,
               last_login_at = excluded.last_login_at""",
        (steam_id, persona_name, avatar_url, now, now),
    )
    db.commit()
    return get_by_steam_id(steam_id)


def get_by_steam_id(steam_id: str) -> dict | None:
    row = get_db().execute(
        "SELECT steam_id, persona_name, avatar_url, created_at, last_login_at"
        " FROM users WHERE steam_id = %s",
        (steam_id,),
    ).fetchone()
    return dict(row) if row is not None else None
