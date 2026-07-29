"""Who can see, join, and control a scrim's server.

Two rules that deliberately pull in opposite directions:

- **Access widens to both teams.** A match has two sides and both have to get onto the
  server. If the team that claimed a listing could not see the address, the server would
  be useless to half the people playing on it.
- **Control narrows to the organising team's leaders.** Settings, console and extension
  belong to leaders of the team that proposed the scrim or posted the listing.

Which means control can sit with someone who did not pay. That is the rule as specified
and it is asserted below, because it is surprising enough to be worth pinning.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app import credits
from app import servers_store as store
from tests.conftest import rgl_team

# Proposing team (organisers) and the team that claims.
HOST_LEADER = "76561198000000010"
HOST_PLAYER = "76561198000000011"
GUEST_LEADER = "76561198000000020"
GUEST_PLAYER = "76561198000000021"
OUTSIDER = "76561198000000030"
HOST_TEAM, GUEST_TEAM, OTHER_TEAM = 101, 202, 303


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def seed_roster(app, team_id, leaders=(), players=()):
    """Leadership comes from RGL's cached roster, so tests seed it there."""
    from app.db import get_db
    with app.test_request_context():
        db = get_db()
        for steam_id in list(leaders) + list(players):
            db.execute(
                "INSERT OR REPLACE INTO rgl_rosters (rgl_team_id, steam_id, name, is_leader)"
                " VALUES (?, ?, ?, ?)",
                (team_id, steam_id, f"p{steam_id[-3:]}", 1 if steam_id in leaders else 0))
        db.commit()


@pytest.fixture
def match(app, client, login, link_team):
    """A confirmed scrim: HOST_TEAM proposed, GUEST_TEAM claimed. Server paid for and
    owned by the guest side, to make the payer/controller split visible."""
    from app.db import get_db

    for steam_id, team in ((HOST_LEADER, HOST_TEAM), (HOST_PLAYER, HOST_TEAM),
                           (GUEST_LEADER, GUEST_TEAM), (GUEST_PLAYER, GUEST_TEAM),
                           (OUTSIDER, OTHER_TEAM)):
        login(steam_id, f"u{steam_id[-3:]}")
        link_team(steam_id, [rgl_team(team, f"Team{team}", None, "sixes")])

    seed_roster(app, HOST_TEAM, leaders=[HOST_LEADER], players=[HOST_PLAYER])
    seed_roster(app, GUEST_TEAM, leaders=[GUEST_LEADER], players=[GUEST_PLAYER])

    now = datetime.now(timezone.utc)
    with app.test_request_context():
        db = get_db()
        cur = db.execute(
            """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                   opponent_team_id, status, created_by,
                                   created_at, updated_at)
               VALUES ('sixes', ?, 'listing', ?, ?, 'confirmed', ?, ?, ?)""",
            ((now + timedelta(days=1)).isoformat(timespec="seconds"), HOST_TEAM,
             GUEST_TEAM, HOST_LEADER, now.isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds")))
        scrim_id = cur.lastrowid
        db.commit()

        # The GUEST paid, so the server is bound to and owned by their side.
        server_id = store.create_server(
            owner_steam_id=GUEST_LEADER, team_id=GUEST_TEAM, scrim_id=scrim_id,
            name="Match server", map_name="cp_process_final", max_slots=24,
            state=store.RUNNING, address="10.0.0.9:27015", players=12,
            join_password="hunter2",
            window_starts_at=(now - timedelta(minutes=10)).isoformat(timespec="seconds"),
            window_ends_at=(now + timedelta(minutes=50)).isoformat(timespec="seconds"))
        credits.grant(GUEST_LEADER, 5, "test"); get_db().commit()
    return {"scrim_id": scrim_id, "server_id": server_id}


# --- access: both sides of the match -------------------------------------------------

@pytest.mark.parametrize("steam_id, who", [
    (HOST_LEADER, "host leader"),
    (HOST_PLAYER, "host player"),
    (GUEST_LEADER, "guest leader"),
    (GUEST_PLAYER, "guest player"),
])
def test_everyone_playing_the_match_can_see_the_server(client, match, steam_id, who):
    as_user(client, steam_id)
    assert client.get(f"/servers/{match['server_id']}").status_code == 200, who
    assert "Match server" in client.get("/servers").get_data(as_text=True), who


@pytest.mark.parametrize("steam_id", [HOST_PLAYER, GUEST_PLAYER, HOST_LEADER])
def test_everyone_playing_gets_the_connect_command(client, match, steam_id):
    """The whole point: a claiming team that cannot see the address cannot play."""
    as_user(client, steam_id)
    for path in (f"/servers/{match['server_id']}", "/servers",
                 f"/scrims/{match['scrim_id']}"):
        body = client.get(path).get_data(as_text=True)
        assert 'connect 10.0.0.9:27015; password &#34;hunter2&#34;' in body \
            or 'connect 10.0.0.9:27015; password "hunter2"' in body, path


def test_a_team_in_neither_side_sees_nothing(client, match):
    as_user(client, OUTSIDER)
    assert client.get(f"/servers/{match['server_id']}").status_code == 404
    assert "Match server" not in client.get("/servers").get_data(as_text=True)


# --- control: the organising team's leaders only -------------------------------------

def test_the_host_leader_controls_the_server(client, match):
    as_user(client, HOST_LEADER)
    body = client.get(f"/servers/{match['server_id']}").get_data(as_text=True)
    assert "Save settings" in body
    assert "Admin console" in body

    resp = client.post(f"/servers/{match['server_id']}/settings", data={
        "map": "cp_snakewater_final1", "join_password": "hunter2"})
    assert resp.status_code in (200, 302)
    with client.application.test_request_context():
        assert store.get_server(match["server_id"])["map"] == "cp_snakewater_final1"


def test_the_paying_guest_leader_does_not_control_it(client, match):
    """The surprising one, asserted on purpose. The guest side paid for and owns this
    server, but the host team organised the scrim, so control is theirs."""
    as_user(client, GUEST_LEADER)
    body = client.get(f"/servers/{match['server_id']}").get_data(as_text=True)
    assert "Save settings" not in body
    assert "Admin console" not in body
    assert "can see and join this server" in body

    assert client.post(f"/servers/{match['server_id']}/settings", data={
        "map": "cp_badlands", "join_password": "x"}).status_code == 404
    assert client.post(f"/servers/{match['server_id']}/console",
                       data={"command": "status"}).status_code == 404


@pytest.mark.parametrize("steam_id", [HOST_PLAYER, GUEST_PLAYER])
def test_ordinary_players_on_either_side_cannot_control_it(client, match, steam_id):
    as_user(client, steam_id)
    assert client.post(f"/servers/{match['server_id']}/settings", data={
        "map": "cp_badlands"}).status_code == 404
    assert client.post(f"/servers/{match['server_id']}/console",
                       data={"command": "status"}).status_code == 404


def test_extending_is_a_control_action_charged_to_whoever_does_it(client, match, app):
    """A host leader with no credits cannot extend; the guest who has them cannot either,
    because extending is control. So it needs a host leader who holds credits."""
    as_user(client, HOST_LEADER)
    assert client.post(f"/servers/{match['server_id']}/extend",
                       follow_redirects=True).status_code == 200
    with app.test_request_context():
        # No credits, so nothing was spent and no time added.
        assert credits.available_credits(HOST_LEADER) == 0

    with app.test_request_context():
        from app.db import get_db
        credits.grant(HOST_LEADER, 2, "test"); get_db().commit()
    client.post(f"/servers/{match['server_id']}/extend")
    with app.test_request_context():
        assert credits.available_credits(HOST_LEADER) == 1     # charged the actor
        assert credits.available_credits(GUEST_LEADER) == 5    # not the owner


def test_the_guest_cannot_extend_even_holding_credits(client, match, app):
    as_user(client, GUEST_LEADER)
    assert client.post(f"/servers/{match['server_id']}/extend").status_code == 404
    with app.test_request_context():
        assert credits.available_credits(GUEST_LEADER) == 5    # untouched


# --- the no-roster fallback ----------------------------------------------------------

def test_with_no_cached_roster_the_owner_keeps_control(client, app, login, link_team):
    """Leadership comes from RGL's roster cache. If RGL was never reachable for a team,
    no leader is known — and a server nobody can control is worse than one its payer
    controls, so the owner holds it until a roster arrives."""
    from app.db import get_db
    owner = login("76561198000000040", "Owner")
    link_team(owner, [rgl_team(OTHER_TEAM, "Solo", None, "sixes")])
    now = datetime.now(timezone.utc)
    with app.test_request_context():
        server_id = store.create_server(
            owner_steam_id=owner, team_id=OTHER_TEAM, name="Unrostered",
            map_name="cp_x", max_slots=24, state=store.RUNNING,
            address="10.0.0.1:27015",
            window_starts_at=now.isoformat(timespec="seconds"),
            window_ends_at=(now + timedelta(minutes=30)).isoformat(timespec="seconds"))
        assert store.team_leaders(OTHER_TEAM) == set()

    as_user(client, owner)
    assert "Save settings" in client.get(f"/servers/{server_id}").get_data(as_text=True)


def test_a_leader_of_the_wrong_team_never_gains_control(client, match, app):
    """The fallback must not be a hole: seeding OUTSIDER as a leader of some unrelated
    team gives them nothing here."""
    seed_roster(app, OTHER_TEAM, leaders=[OUTSIDER])
    as_user(client, OUTSIDER)
    assert client.get(f"/servers/{match['server_id']}").status_code == 404


# --- the connect command itself -----------------------------------------------------

def test_no_connect_command_before_the_server_is_running(app, match):
    with app.test_request_context():
        store.set_state(match["server_id"], store.SCHEDULED)
        server = store.get_server(match["server_id"])
        assert store.connect_command(server) is None


def test_a_password_free_server_gets_a_bare_connect(app, match):
    with app.test_request_context():
        store.update_settings(match["server_id"], name="Match server",
                              map_name="cp_x", max_slots=24, join_password=None)
        server = store.get_server(match["server_id"])
        assert store.connect_command(server) == "connect 10.0.0.9:27015"


def test_a_password_with_a_space_is_quoted(app, match):
    """An unquoted password containing a space or semicolon would break the console
    command, which is exactly the sort of thing nobody notices until match time."""
    with app.test_request_context():
        store.update_settings(match["server_id"], name="Match server", map_name="cp_x",
                              max_slots=24, join_password="let me in")
        server = store.get_server(match["server_id"])
        assert store.connect_command(server) == \
            'connect 10.0.0.9:27015; password "let me in"'
