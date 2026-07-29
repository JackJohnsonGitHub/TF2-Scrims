"""User Story 1: a team sees the servers it is entitled to, and nobody else's.

Independently testable with no payment, no credits and no scheduling — servers are
seeded rows, which is the whole point of US1 being the MVP.
"""
from app.models import DEMO_OWNER_STEAM_ID, DEMO_TEAM_ID
from tests.conftest import rgl_team

RUNNING, STOPPED = "Friday Night PUG", "Jump Practice"


def on_team(login, link_team, as_owner=False):
    steam_id = login(DEMO_OWNER_STEAM_ID) if as_owner else login()
    link_team(steam_id, [rgl_team(DEMO_TEAM_ID, "Server Owners", "SRV", "sixes")])
    return steam_id


def test_inventory_shows_state_and_connect_details(client, login, link_team,
                                                   demo_servers):
    on_team(login, link_team)
    demo_servers()

    body = client.get("/servers").get_data(as_text=True)
    assert RUNNING in body and STOPPED in body
    assert "Running" in body and "Stopped" in body
    assert "10.0.0.5:27015" in body          # the running one is joinable
    assert "12/24" in body                   # players against capacity


def test_a_stopped_server_says_why_rather_than_rendering_blank(client, login,
                                                               link_team,
                                                               demo_servers):
    """An ambiguous row is the failure this guards: a team needs to tell "your time
    ran out" from "something broke"."""
    on_team(login, link_team)
    ids = demo_servers()

    body = client.get(f"/servers/{ids[1]}").get_data(as_text=True)
    assert "Stopped because its time ran out" in body


def test_unknown_live_state_is_not_reported_as_stopped(client, login, link_team, app):
    """When the cluster cannot be reached we do not know the player count. Reporting
    that as an empty server would be a lie; it has to read as unknown."""
    from app.db import get_db
    steam_id = on_team(login, link_team)
    now = "2026-07-29T00:00:00+00:00"
    with app.test_request_context():
        get_db().execute(
            """INSERT INTO servers (owner_steam_id, team_id, state, name, map,
                                    max_slots, players, created_at, updated_at)
               VALUES (?,?, 'unknown', 'Mystery', 'cp_x', 24, NULL, ?, ?)""",
            (steam_id, DEMO_TEAM_ID, now, now))
        get_db().commit()

    body = client.get("/servers").get_data(as_text=True)
    assert "?/24" in body
    assert "Unknown" in body


def test_another_teams_servers_are_absent_and_404(client, login, link_team,
                                                  demo_servers):
    ids = demo_servers()
    steam_id = login()
    link_team(steam_id, [rgl_team(4242, "Other", "OTH", "sixes")])

    body = client.get("/servers").get_data(as_text=True)
    assert RUNNING not in body and STOPPED not in body
    for sid in ids:
        assert client.get(f"/servers/{sid}").status_code == 404


def test_empty_state_leads_with_scheduling_being_free(client, login, link_team):
    """FR-012. A first-time visitor should come away knowing the scrim surface costs
    nothing, and that a server is bought rather than created."""
    on_team(login, link_team)

    body = client.get("/servers").get_data(as_text=True)
    assert "No servers yet" in body
    assert "free" in body.lower()
    assert "credits" in body.lower()
    assert "Create server" not in body


def test_unlinked_viewer_is_asked_to_link_rgl(client, login, demo_servers):
    demo_servers()
    login()

    body = client.get("/servers").get_data(as_text=True)
    assert "Link your RGL account" in body
    assert RUNNING not in body


def test_the_admin_password_is_never_in_a_response(client, login, link_team,
                                                   demo_servers, app):
    """FR-009 / SC-009. The RCON password is deliberately not a column on `servers`,
    so this asserts the property the schema is meant to guarantee."""
    from app.db import get_db
    on_team(login, link_team, as_owner=True)
    ids = demo_servers()

    with app.test_request_context():
        columns = {r[1] for r in get_db().execute("PRAGMA table_info(servers)")}
    assert not {"rcon_password", "admin_password"} & columns

    for path in ("/servers", f"/servers/{ids[0]}"):
        body = client.get(path).get_data(as_text=True).lower()
        assert "rcon_password" not in body
        assert "rcon password" not in body


def test_demo_servers_stay_labelled(client, login, link_team, demo_servers):
    on_team(login, link_team)
    demo_servers()
    assert ">DEMO<" in client.get("/servers").get_data(as_text=True)
