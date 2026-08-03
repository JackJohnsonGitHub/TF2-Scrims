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
               VALUES (%s,%s, 'unknown', 'Mystery', 'cp_x', 24, NULL, %s, %s)""",
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
        columns = {r["column_name"] for r in get_db().execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'servers'")}
    assert not {"rcon_password", "admin_password"} & columns

    for path in ("/servers", f"/servers/{ids[0]}"):
        body = client.get(path).get_data(as_text=True).lower()
        assert "rcon_password" not in body
        assert "rcon password" not in body


def test_demo_servers_stay_labelled(client, login, link_team, demo_servers):
    on_team(login, link_team)
    demo_servers()
    assert ">DEMO<" in client.get("/servers").get_data(as_text=True)


def test_a_per_scrim_server_only_offers_settings_that_matter_for_the_match(
        client, login, link_team, app, demo_servers):
    """FR-028. Renaming or resizing a server that exists for one hour of one match is
    noise, and the route ignores a posted name or slot count rather than trusting it."""
    from datetime import datetime, timedelta, timezone

    from app.db import get_db
    steam_id = on_team(login, link_team, as_owner=True)
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        db = get_db()
        db.execute(
            # An explicit id does not advance the identity sequence, so a later
            # auto-generated scrim in the same test would collide (research R7). Safe
            # here: 500 is far above the sequence, which per-test RESTART IDENTITY puts
            # back at 1, and this test generates no other scrim. Keep it that way.
            "INSERT INTO scrims (id, format, scheduled_at, origin, proposer_team_id,"
            " status, created_by, created_at, updated_at) VALUES"
            " (500, 'sixes', %s, 'listing', %s, 'open', %s, %s, %s)",
            ((now + timedelta(days=1)).isoformat(timespec="seconds"), DEMO_TEAM_ID,
             steam_id, now.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")))
        cur = db.execute(
            """INSERT INTO servers (scrim_id, owner_steam_id, team_id, state, name, map,
                                    max_slots, created_at, updated_at)
               VALUES (500, %s, %s, 'running', 'Match server', 'cp_process_final', 24,
                       %s, %s)
               RETURNING id""",
            (steam_id, DEMO_TEAM_ID, now.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")))
        server_id = cur.fetchone()["id"]
        db.commit()

    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert 'name="map"' in body                  # the one that matters mid-match
    assert 'name="join_password"' in body
    assert 'name="max_slots"' not in body
    assert 'name="name"' not in body

    # A forged post cannot rename or resize it either.
    client.post(f"/servers/{server_id}/settings", data={
        "name": "Hijacked", "map": "cp_snakewater_final1", "max_slots": "4"})
    with app.test_request_context():
        from app import servers_store as store
        server = store.get_server(server_id)
    assert server["name"] == "Match server"
    assert server["max_slots"] == 24
    assert server["map"] == "cp_snakewater_final1"    # the allowed change did apply


def test_a_season_term_server_states_when_its_term_ends(client, login, link_team, app):
    """FR-011: a rented server must never simply vanish on its owner. Display only —
    the constitution leaves the season-term purchase unit undefined, so nothing can
    create one of these yet."""
    from datetime import datetime, timedelta, timezone

    from app.db import get_db
    steam_id = on_team(login, link_team, as_owner=True)
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        cur = get_db().execute(
            """INSERT INTO servers (owner_steam_id, team_id, state, name, map,
                                    max_slots, term_ends_at, created_at, updated_at)
               VALUES (%s, %s, 'running', 'Season home', 'cp_process_final', 24, %s, %s, %s)
               RETURNING id""",
            (steam_id, DEMO_TEAM_ID,
             (now + timedelta(days=30)).isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")))
        server_id = cur.fetchone()["id"]
        get_db().commit()

    body = client.get(f"/servers/{server_id}").get_data(as_text=True)
    assert "Season term ends" in body
    assert "suspended" in body
    assert 'name="name"' in body      # a rental is configurable, unlike a match server
