"""Shared test fixtures: an app on a throwaway SQLite DB, a client, and a login helper."""
import pytest

from app import create_app
from app.config import Config


@pytest.fixture
def app(tmp_path):
    class TestConfig(Config):
        DB_PATH = str(tmp_path / "test.db")
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
