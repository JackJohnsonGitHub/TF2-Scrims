"""Integration smoke tests for the app shell. Owner-only screens now require sign-in
(feature 002), so those tests use the `login` fixture. Fixtures live in tests/conftest.py."""
from app.models import SAMPLE_SERVERS


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data == b"ok"


def test_root_anonymous_shows_landing(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'data-screen="landing"' in resp.data


def test_dashboard_when_signed_in(client, login):
    login()
    resp = client.get("/")
    assert resp.status_code == 200
    assert b'data-screen="dashboard"' in resp.data


def test_server_list_renders(client, login):
    login()
    resp = client.get("/servers")
    assert resp.status_code == 200
    assert b'data-screen="servers-list"' in resp.data


def test_create_server_form_renders(client, login):
    login()
    resp = client.get("/servers/new")
    assert resp.status_code == 200
    assert b'data-screen="server-new"' in resp.data
    assert b'name="max_slots"' in resp.data


def test_server_detail_renders(client, login):
    login()
    resp = client.get(f"/servers/{SAMPLE_SERVERS[0].id}")
    assert resp.status_code == 200
    assert b'data-screen="server-detail"' in resp.data
    assert b"Settings" in resp.data
    assert b"Admin console" in resp.data


def test_demo_servers_are_tagged(client, login):
    login()
    assert b">DEMO<" in client.get("/servers").data
    assert b">DEMO<" in client.get(f"/servers/{SAMPLE_SERVERS[0].id}").data


def test_unknown_path_is_404(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert b'data-screen="not-found"' in resp.data


def test_unknown_server_is_404(client, login):
    login()
    assert client.get("/servers/does-not-exist").status_code == 404


def test_create_validation_rejects_bad_slots(client, login):
    login()
    resp = client.post("/servers/new", data={"name": "X", "map": "cp_x", "max_slots": "999"})
    assert resp.status_code == 400
    assert b"Max slots must be between" in resp.data


def test_console_echoes_command(client, login):
    login()
    resp = client.post(f"/servers/{SAMPLE_SERVERS[0].id}/console", data={"command": "status"})
    assert resp.status_code == 200
    assert b"status" in resp.data
    assert b"Placeholder response" in resp.data
