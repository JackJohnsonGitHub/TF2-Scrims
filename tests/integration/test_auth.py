"""Integration tests for Steam sign-in — Steam calls are mocked (no network)."""
import sqlite3

import app.routes.auth as auth_routes

STEAM_ID = "76561198000000123"


def _mock_verify(monkeypatch, result):
    monkeypatch.setattr(auth_routes, "verify_return", lambda params: result)


def _mock_summary(monkeypatch, persona="Tester", avatar="http://avatar/x.jpg"):
    monkeypatch.setattr(auth_routes, "fetch_summary", lambda sid, key: (persona, avatar))


def test_login_redirects_to_steam(client):
    resp = client.get("/login")
    assert resp.status_code == 302
    assert "steamcommunity.com/openid/login" in resp.headers["Location"]


def test_valid_return_creates_user_and_session(client, app, monkeypatch):
    _mock_verify(monkeypatch, STEAM_ID)
    _mock_summary(monkeypatch, persona="Rocket Jumper")

    resp = client.get("/login/return?openid.claimed_id=x")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")  # dashboard

    # A users row now exists and the header shows the persona.
    rows = sqlite3.connect(app.config["DB_PATH"]).execute(
        "SELECT persona_name FROM users WHERE steam_id = ?", (STEAM_ID,)
    ).fetchall()
    assert rows == [("Rocket Jumper",)]
    assert b"Rocket Jumper" in client.get("/").data


def test_invalid_return_sets_no_session(client, monkeypatch):
    _mock_verify(monkeypatch, None)  # verification failed / forged
    resp = client.get("/login/return?openid.claimed_id=forged")
    assert resp.status_code == 400
    assert b"Sign-in didn't complete" in resp.data
    # Still anonymous: owner-only area redirects to sign-in.
    assert client.get("/servers").status_code == 302


def test_returning_user_is_single_account(client, app, monkeypatch):
    _mock_verify(monkeypatch, STEAM_ID)
    _mock_summary(monkeypatch)
    client.get("/login/return?openid.claimed_id=x")
    client.get("/logout")
    client.get("/login/return?openid.claimed_id=x")  # sign in again
    count = sqlite3.connect(app.config["DB_PATH"]).execute(
        "SELECT COUNT(*) FROM users WHERE steam_id = ?", (STEAM_ID,)
    ).fetchone()[0]
    assert count == 1


def test_guard_redirects_with_next_and_returns(client, monkeypatch):
    # Anonymous access to an owner-only area redirects to sign-in with ?next=.
    resp = client.get("/servers")
    assert resp.status_code == 302
    assert "/login?next=/servers" in resp.headers["Location"]

    # Completing sign-in returns to the originally requested area.
    _mock_verify(monkeypatch, STEAM_ID)
    _mock_summary(monkeypatch)
    client.get("/login?next=/servers")
    ret = client.get("/login/return?openid.claimed_id=x")
    assert ret.headers["Location"].endswith("/servers")


def test_next_rejects_external_redirect(client, monkeypatch):
    _mock_verify(monkeypatch, STEAM_ID)
    _mock_summary(monkeypatch)
    client.get("/login?next=https://evil.example.com/phish")
    ret = client.get("/login/return?openid.claimed_id=x")
    # External target ignored → falls back to the dashboard.
    assert ret.headers["Location"].endswith("/")


def test_logout_clears_session(client, login):
    login()
    assert client.get("/servers").status_code == 200
    client.get("/logout")
    assert client.get("/servers").status_code == 302  # locked again


def test_session_persists_across_requests(client, login):
    login()
    for _ in range(10):
        assert client.get("/").status_code == 200
        assert b'data-screen="dashboard"' in client.get("/").data


def test_absent_session_is_anonymous(client):
    # A fresh client with no session is treated as signed out (FR-010 family).
    assert client.get("/servers").status_code == 302
    assert b'data-screen="landing"' in client.get("/").data
