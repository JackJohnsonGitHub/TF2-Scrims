"""Shared test fixtures: an app on a real PostgreSQL, a client, and a login helper.

**The suite runs against a real store.** One engine everywhere — development, tests, and
deployment (FR-025) — so there is no in-memory substitute and no second dialect. The cost
is that running the tests requires a running Postgres; the benefit is that a test which
passes here exercises the same integrity guarantees the deployed platform relies on, which
is the whole point of FR-026.

Isolation is per-test `TRUNCATE … RESTART IDENTITY CASCADE` rather than a throwaway file
(FR-027). `RESTART IDENTITY` matters: it resets the sequences, so tests asserting on
specific ids behave exactly as they did with a fresh SQLite file.
"""
import pytest


def pytest_sessionstart(session):
    """Fail the run once, actionably, when no store is reachable (FR-024).

    Without this, 408 tests each fail with a connection error and the run reads like the
    code is broken rather than like the developer has not started a container. FR-024 is
    explicit that this must not be the experience.
    """
    from app import db

    try:
        db.check()
    except Exception as exc:  # noqa: BLE001 — any failure to reach the store is fatal here
        pytest.exit(
            "\n\n"
            "Cannot reach the metadata store, so the test suite cannot run.\n"
            "The suite runs against a real PostgreSQL — one engine everywhere (FR-025).\n\n"
            f"  store:  {db.redact_dsn()}\n"
            f"  error:  {type(exc).__name__}: {exc}\n\n"
            "Start one and re-run:\n\n"
            "  docker run -d --name tf2-pg -p 5432:5432 \\\n"
            "    -e POSTGRES_PASSWORD=dev -e POSTGRES_USER=tf2app "
            "-e POSTGRES_DB=tf2hosting \\\n"
            "    postgres:17-alpine\n\n"
            '  export DATABASE_URL="postgresql://tf2app:dev@localhost:5432/tf2hosting"\n\n'
            "If the container already exists but is stopped:  docker start tf2-pg\n",
            returncode=1,
        )


@pytest.fixture(scope="session", autouse=True)
def _store():
    """Bring the store to the current schema once for the whole session."""
    import psycopg

    from app import db

    db.migrate()

    # Discovered rather than hardcoded: a table added by a later migration must be
    # truncated too, and a list in this file would silently not be updated — leaving one
    # table leaking state between tests, which is the exact failure FR-027 forbids.
    with psycopg.connect(db.dsn()) as conn:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables"
                " WHERE schemaname = 'public' AND tablename <> 'schema_migrations'"
                " ORDER BY tablename"
            ).fetchall()
        ]
    truncate_sql = (
        f"TRUNCATE {', '.join(names)} RESTART IDENTITY CASCADE" if names else None
    )

    with psycopg.connect(db.dsn(), autocommit=True) as conn:
        yield truncate_sql, conn

    db.close_pool()


@pytest.fixture(autouse=True)
def _clean_store(_store):
    """Empty every table before each test, and reset every identity sequence."""
    truncate_sql, conn = _store
    if truncate_sql:
        conn.execute(truncate_sql)


@pytest.fixture
def app():
    from app import create_app
    from app.config import Config

    class TestConfig(Config):
        SECRET_KEY = "test-secret"
        STEAM_API_KEY = ""
        BASE_URL = "http://localhost:5000"
        ENV = "development"

    application = create_app(TestConfig)
    application.config.update(TESTING=True)
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def demo_servers(app):
    """Seed two servers for a team — one running, one stopped — and return their ids.

    Servers are persisted rows as of feature 005, so tests create them rather than
    importing a module-level sample list. Defaults to the demo rival team so the
    access rule is exercised honestly: they are somebody else's servers unless the
    viewer is on that team.
    """
    def _seed(team_id=None, owner=None, running_name="Friday Night PUG",
              stopped_name="Jump Practice", demo=True):
        from app.db import get_db
        from app.models import DEMO_OWNER_STEAM_ID, DEMO_TEAM_ID
        team_id = DEMO_TEAM_ID if team_id is None else team_id
        owner = DEMO_OWNER_STEAM_ID if owner is None else owner
        now = "2026-07-29T00:00:00+00:00"
        ids = []
        with app.test_request_context():
            db = get_db()
            db.execute(
                "INSERT INTO users (steam_id, persona_name, created_at,"
                " last_login_at) VALUES (%s, 'Demo Rival', %s, %s)"
                " ON CONFLICT DO NOTHING", (owner, now, now))
            db.execute(
                "INSERT INTO rgl_teams (rgl_team_id, name, format, updated_at)"
                " VALUES (%s, 'Demo Rival', 'sixes', %s)"
                " ON CONFLICT DO NOTHING", (team_id, now))
            for name, map_name, slots, state, address, players, reason in (
                (running_name, "cp_process_final", 24, "running", "10.0.0.5:27015", 12, None),
                (stopped_name, "jump_academy_b4", 8, "stopped", None, None, "time_expired"),
            ):
                row = db.execute(
                    """INSERT INTO servers (owner_steam_id, team_id, state, name, map,
                                            max_slots, address, players, demo,
                                            stopped_reason, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       RETURNING id""",
                    (owner, team_id, state, name, map_name, slots, address, players,
                     int(demo), reason, now, now),
                ).fetchone()
                ids.append(row["id"])
            db.commit()
        return ids

    return _seed


@pytest.fixture
def login(app, client):
    """Sign a user in: create the account row and set the session steam_id."""
    def _login(steam_id="76561198000000001", persona="Tester", avatar=None):
        with app.test_request_context():
            from app.accounts import upsert_on_login
            upsert_on_login(steam_id, persona, avatar)
        with client.session_transaction() as sess:
            sess["steam_id"] = steam_id
        return steam_id

    return _login


def rgl_team(team_id=101, name="Alpha", tag="ALP", fmt="sixes",
             division="RGL-Amateur", season=140):
    """Build an RglTeam for canned profiles."""
    from app.rgl import RglTeam
    return RglTeam(rgl_team_id=team_id, name=name, tag=tag, format=fmt,
                   division_name=division, season_id=season)


@pytest.fixture
def mock_rgl(monkeypatch):
    """Patch the RGL client to a canned outcome (routes call `rgl.fetch_profile`
    through the module, so patching `app.rgl.fetch_profile` covers everything)."""
    def _mock(outcome="ok", name="Player One", teams=(), verified=False,
              banned=False, probation=False):
        from app.rgl import RglProfile
        if outcome in ("no_profile", "unavailable"):
            profile = RglProfile(outcome=outcome)
        else:
            profile = RglProfile(outcome="ok", name=name, is_verified=verified,
                                 is_banned=banned, is_on_probation=probation,
                                 teams=list(teams))
        monkeypatch.setattr("app.rgl.fetch_profile", lambda steam_id: profile)
        return profile

    return _mock


@pytest.fixture
def link_team(app):
    """Link a user directly through the store (no HTTP): create their account,
    store the given teams, and grant membership. Setup helper for scrim tests."""
    def _link(steam_id, teams, persona=None):
        from app.accounts import upsert_on_login
        from app.rgl import RglProfile
        from app.rgl_store import save_link
        with app.test_request_context():
            upsert_on_login(steam_id, persona or f"Player {steam_id[-4:]}", None)
            save_link(steam_id, RglProfile(outcome="ok", name=persona or "Player",
                                           teams=list(teams)))
        return steam_id

    return _link
