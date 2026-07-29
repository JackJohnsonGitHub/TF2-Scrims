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

-- feature 005: payment, credits, and servers. See specs/005-servers-page/data-model.md.

-- A user's own Steam trade URL. Its token is what lets us ask Steam whether a trade
-- from this user would be held, so it is a precondition of paying, not a nicety.
CREATE TABLE IF NOT EXISTS steam_trade_links (
    steam_id      TEXT PRIMARY KEY REFERENCES users(steam_id),
    trade_url     TEXT NOT NULL,
    partner_id    TEXT NOT NULL,
    access_token  TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- One attempt to pay, by any method. `method` is what keeps the model open to
-- payment methods beyond Steam trades without reworking entitlement.
--
-- UNIQUE (method, provider_ref) is the exactly-once guarantee for crediting. The
-- poller re-reads the same offers on every run and can be run twice by hand, so
-- idempotency cannot rest on it behaving well — the store enforces it.
CREATE TABLE IF NOT EXISTS payments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_id         TEXT NOT NULL REFERENCES users(steam_id),
    method           TEXT NOT NULL,
    provider_ref     TEXT,
    state            TEXT NOT NULL,
    state_reason     TEXT,
    items_expected   INTEGER NOT NULL,
    items_received   INTEGER,
    credits_granted  INTEGER,
    hold_until       TEXT,
    target_scrim_id  INTEGER REFERENCES scrims(id),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (method, provider_ref)
);

-- A server a team is entitled to. State is real; the compute behind it is simulated
-- this increment and replaced behind the same seam by feature 006.
--
-- The RCON/administrative password is deliberately absent: it belongs in the secret
-- store and must never be selectable into a template context.
CREATE TABLE IF NOT EXISTS servers (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scrim_id          INTEGER REFERENCES scrims(id),
    owner_steam_id    TEXT NOT NULL REFERENCES users(steam_id),
    team_id           INTEGER REFERENCES rgl_teams(rgl_team_id),
    state             TEXT NOT NULL,
    name              TEXT NOT NULL,
    map               TEXT NOT NULL,
    max_slots         INTEGER NOT NULL,
    join_password     TEXT,
    address           TEXT,
    players           INTEGER,
    window_starts_at  TEXT,
    window_ends_at    TEXT,
    grace_used        INTEGER NOT NULL DEFAULT 0,
    demo              INTEGER NOT NULL DEFAULT 0,
    stopped_reason    TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_scrim ON servers(scrim_id)
    WHERE scrim_id IS NOT NULL;

-- Append-only. The single source of truth for every balance: available credits are
-- SUM(delta), never a cached column that could disagree with these rows and leave
-- the ledger untrustworthy for exactly the dispute it exists to settle.
CREATE TABLE IF NOT EXISTS credit_ledger (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    steam_id    TEXT NOT NULL REFERENCES users(steam_id),
    delta       INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    cause       TEXT NOT NULL,
    payment_id  INTEGER REFERENCES payments(id),
    scrim_id    INTEGER REFERENCES scrims(id),
    server_id   INTEGER REFERENCES servers(id),
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_credit_ledger_steam_id ON credit_ledger(steam_id);
"""


# Wait this long for a competing writer before giving up. SQLite's default is 0 —
# a busy database fails instantly rather than waiting.
BUSY_TIMEOUT_MS = 5000


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with the pragmas this app depends on.

    Every connection — request-scoped or CLI — MUST come through here. The payment
    poller runs as a separate process from Gunicorn's workers, so writes genuinely
    contend:

    - `WAL` lets readers proceed while a writer holds the log. The default journal
      mode takes a whole-database exclusive lock instead, so a page load during a
      credit write would simply fail.
    - `busy_timeout` turns "database is locked" into a bounded wait. Without it the
      default is zero and a contended write raises immediately — which, on the
      payment path, would present as a trade that silently never got credited.
    - `foreign_keys` is OFF by default in SQLite, which has quietly made every
      REFERENCES clause in SCHEMA decorative. The credit tables depend on
      referential integrity far more than the existing ones do.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    """Per-request SQLite connection, stored on Flask's `g`."""
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_schema(app) -> None:
    """Create tables if absent. Idempotent; safe to call on every startup."""
    conn = connect(app.config["DB_PATH"])
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
