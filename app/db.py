"""SQLite connection + schema for the metadata store.

First persisted entity is the user account (see specs/002-steam-sign-in/data-model.md).
A thin stdlib-`sqlite3` seam keeps this minimal now while leaving room to move to
Postgres/an ORM later.
"""
import sqlite3

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    steam_id       TEXT PRIMARY KEY,
    persona_name   TEXT,
    avatar_url     TEXT,
    created_at     TEXT NOT NULL,
    last_login_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rgl_links (
    steam_id           TEXT PRIMARY KEY REFERENCES users(steam_id),
    profile_name       TEXT,
    state              TEXT NOT NULL,
    is_verified        INTEGER NOT NULL DEFAULT 0,
    is_banned          INTEGER NOT NULL DEFAULT 0,
    is_on_probation    INTEGER NOT NULL DEFAULT 0,
    linked_at          TEXT NOT NULL,
    last_refreshed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rgl_teams (
    rgl_team_id    INTEGER PRIMARY KEY,
    name           TEXT NOT NULL,
    tag            TEXT,
    format         TEXT NOT NULL,
    division_name  TEXT,
    season_id      INTEGER,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rgl_memberships (
    steam_id     TEXT NOT NULL REFERENCES users(steam_id),
    rgl_team_id  INTEGER NOT NULL REFERENCES rgl_teams(rgl_team_id),
    PRIMARY KEY (steam_id, rgl_team_id)
);

CREATE TABLE IF NOT EXISTS scrims (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    format            TEXT NOT NULL,
    scheduled_at      TEXT NOT NULL,
    origin            TEXT NOT NULL,
    proposer_team_id  INTEGER NOT NULL REFERENCES rgl_teams(rgl_team_id),
    opponent_team_id  INTEGER REFERENCES rgl_teams(rgl_team_id),
    status            TEXT NOT NULL,
    created_by        TEXT NOT NULL REFERENCES users(steam_id),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    notes             TEXT
);

CREATE TABLE IF NOT EXISTS rgl_rosters (
    rgl_team_id  INTEGER NOT NULL REFERENCES rgl_teams(rgl_team_id),
    steam_id     TEXT NOT NULL,
    name         TEXT NOT NULL,
    is_leader    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (rgl_team_id, steam_id)
);

CREATE TABLE IF NOT EXISTS rgl_roster_meta (
    rgl_team_id  INTEGER PRIMARY KEY REFERENCES rgl_teams(rgl_team_id),
    fetched_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rgl_seasons (
    season_id         INTEGER PRIMARY KEY,
    name              TEXT NOT NULL,
    format            TEXT,
    division_sorting  TEXT NOT NULL DEFAULT '{}',
    fetched_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rgl_season_teams (
    season_id    INTEGER NOT NULL REFERENCES rgl_seasons(season_id),
    rgl_team_id  INTEGER NOT NULL,
    division_id  INTEGER,
    hydrated_at  TEXT,
    PRIMARY KEY (season_id, rgl_team_id)
);

CREATE TABLE IF NOT EXISTS scrim_attendance (
    scrim_id         INTEGER NOT NULL REFERENCES scrims(id),
    player_steam_id  TEXT NOT NULL,
    player_name      TEXT NOT NULL,
    status           TEXT NOT NULL,
    marked_by        TEXT NOT NULL REFERENCES users(steam_id),
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (scrim_id, player_steam_id)
);
"""


def get_db() -> sqlite3.Connection:
    """Per-request SQLite connection, stored on Flask's `g`."""
    if "db" not in g:
        conn = sqlite3.connect(current_app.config["DB_PATH"])
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_schema(app) -> None:
    """Create tables if absent. Idempotent; safe to call on every startup."""
    conn = sqlite3.connect(app.config["DB_PATH"])
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
