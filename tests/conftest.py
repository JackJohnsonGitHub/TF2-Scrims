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
