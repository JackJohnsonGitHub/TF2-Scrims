"""Integration smoke tests for the app shell. Owner-only screens now require sign-in
(feature 002), so those tests use the `login` fixture. Fixtures live in tests/conftest.py.

The "/" dashboard leads with scrims (constitution v3.0.0, Principle I): scheduling is
the free core loop, so the home page opens on the viewer's scrim picture and keeps the
placeholder server content below it.
"""
from datetime import datetime, timedelta, timezone

from app.models import DEMO_OWNER_STEAM_ID, DEMO_TEAM_ID
from tests.conftest import rgl_team

RUNNING, STOPPED = "Friday Night PUG", "Jump Practice"


def on_server_team(login, link_team, demo_servers, as_owner=False):
    """Sign in as someone who may see the demo team's servers, and seed them.

    Servers are persisted rows as of feature 005, so a test creates them rather than
    importing a module-level sample list. `as_owner` signs in as the captain the
    servers were granted to, which is who the settings and console belong to.
    """
    steam_id = login(DEMO_OWNER_STEAM_ID) if as_owner else login()
    link_team(steam_id, [rgl_team(DEMO_TEAM_ID, "Server Owners", "SRV", "sixes")])
    return steam_id, demo_servers()


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


def test_self_service_server_creation_is_gone(client, login):
    """Feature 001 shipped a "+ Create server" form. Constitution v3.1.0 Principle
    VIII leaves no user-completable path to it — a server exists only because credits
    were granted — so the form promised an action nobody could take. Deliberate break
    of 001's spec, recorded in specs/005-servers-page/plan.md."""
    login()
    assert client.get("/servers/new").status_code == 404
    assert client.post("/servers/new", data={"name": "X"}).status_code == 404

    nav = client.get("/servers").get_data(as_text=True)
    assert "Create server" not in nav
    assert "Create your first server" not in nav
    assert "Create server" not in client.get("/").get_data(as_text=True)


def test_server_detail_renders(client, login, link_team, demo_servers):
    _steam_id, ids = on_server_team(login, link_team, demo_servers, as_owner=True)
    resp = client.get(f"/servers/{ids[0]}")
    assert resp.status_code == 200
    assert b'data-screen="server-detail"' in resp.data
    assert b"Settings" in resp.data
    assert b"Admin console" in resp.data


def test_demo_servers_are_tagged(client, login, link_team, demo_servers):
    _steam_id, ids = on_server_team(login, link_team, demo_servers)
    assert b">DEMO<" in client.get("/servers").data
    assert b">DEMO<" in client.get(f"/servers/{ids[0]}").data


# --- Server access: you see only what your own team can join (constitution VIII) ---

def test_servers_of_another_team_are_hidden_from_lists(client, login, link_team,
                                                       demo_servers):
    """A user on some other RGL team sees none of that team's servers, on either
    the home dashboard or the servers list."""
    demo_servers()
    steam_id = login()
    link_team(steam_id, [rgl_team(4242, "Some Other Team", "OTH", "sixes")])

    home = client.get("/").get_data(as_text=True)
    servers = client.get("/servers").get_data(as_text=True)
    for name in (RUNNING, STOPPED):
        assert name not in home
        assert name not in servers
    assert "No servers yet" in servers          # honest empty state, not a filtered table
    assert "Recent servers" not in home


def test_unlinked_user_sees_no_servers(client, login, demo_servers):
    """No RGL team at all means no server is yours — and the page still renders,
    prompting the RGL link rather than showing an inventory."""
    demo_servers()
    login()
    body = client.get("/").get_data(as_text=True)
    assert body.count(RUNNING) == 0
    servers = client.get("/servers")
    assert servers.status_code == 200
    assert b"Link your RGL account" in servers.data


def test_another_teams_server_is_404_not_403(client, login, link_team, demo_servers):
    """Detail, settings and RCON are all indistinguishable from a nonexistent
    server — being told "forbidden" would confirm the server exists."""
    sid = demo_servers()[0]
    steam_id = login()
    link_team(steam_id, [rgl_team(4242, "Some Other Team", "OTH", "sixes")])

    assert client.get(f"/servers/{sid}").status_code == 404
    assert client.post(f"/servers/{sid}/console", data={"command": "status"}).status_code == 404
    assert client.post(f"/servers/{sid}/settings", data={
        "name": "X", "map": "cp_x", "max_slots": "24"}).status_code == 404


def test_unknown_path_is_404(client):
    resp = client.get("/no-such-page")
    assert resp.status_code == 404
    assert b'data-screen="not-found"' in resp.data


def test_unknown_server_is_404(client, login):
    login()
    assert client.get("/servers/does-not-exist").status_code == 404
    assert client.get("/servers/999999").status_code == 404


def test_settings_validation_rejects_bad_slots(client, login, link_team, demo_servers):
    _steam_id, ids = on_server_team(login, link_team, demo_servers, as_owner=True)
    resp = client.post(f"/servers/{ids[0]}/settings", data={
        "name": "X", "map": "cp_x", "max_slots": "999"})
    assert resp.status_code == 400
    assert b"Max slots must be between" in resp.data


def test_settings_persist(client, login, link_team, demo_servers):
    _steam_id, ids = on_server_team(login, link_team, demo_servers, as_owner=True)
    client.post(f"/servers/{ids[0]}/settings", data={
        "name": "Renamed", "map": "cp_gullywash_final1", "max_slots": "18"})
    body = client.get(f"/servers/{ids[0]}").get_data(as_text=True)
    assert "Renamed" in body and "cp_gullywash_final1" in body


def test_console_echoes_command_on_a_running_server(client, login, link_team,
                                                    demo_servers):
    _steam_id, ids = on_server_team(login, link_team, demo_servers, as_owner=True)
    resp = client.post(f"/servers/{ids[0]}/console", data={"command": "status"})
    assert resp.status_code == 200
    assert b"status" in resp.data
    assert b"Placeholder response" in resp.data


def test_console_refuses_when_the_server_is_not_running(client, login, link_team,
                                                        demo_servers):
    """A placeholder reply on a stopped server implies the command landed somewhere."""
    _steam_id, ids = on_server_team(login, link_team, demo_servers, as_owner=True)
    resp = client.post(f"/servers/{ids[1]}/console", data={"command": "status"})
    assert resp.status_code == 200
    assert b"Not sent" in resp.data
    assert b"Placeholder response" not in resp.data


def test_a_teammate_who_is_not_the_owner_gets_no_controls(client, login, link_team,
                                                          demo_servers):
    """Visible and joinable, but settings and console belong to the captain the
    server was granted to (Principle VIII)."""
    _steam_id, ids = on_server_team(login, link_team, demo_servers)  # not the owner
    body = client.get(f"/servers/{ids[0]}").get_data(as_text=True)
    assert "Admin console" not in body
    assert "Save settings" not in body
    assert "can see and join it" in body
    assert client.post(f"/servers/{ids[0]}/settings", data={
        "name": "X", "map": "cp_x", "max_slots": "24"}).status_code == 404
    assert client.post(f"/servers/{ids[0]}/console",
                       data={"command": "status"}).status_code == 404


# --- Scrims lead the home dashboard (constitution v3.0.0, Principles I & VIII) ---

A = "76561198000000001"  # on Alpha, sixes
B = "76561198000000002"  # on Bravo, sixes
C = "76561198000000003"  # on Charlie, sixes

TEAM_A = rgl_team(101, "Alpha", "ALP", "sixes")
TEAM_B = rgl_team(202, "Bravo", "BRV", "sixes")
TEAM_C = rgl_team(303, "Charlie", "CHA", "sixes")


def as_user(client, steam_id):
    with client.session_transaction() as sess:
        sess["steam_id"] = steam_id


def future_iso(days=3):
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def test_home_shows_linked_users_scrim_picture(app, client, link_team):
    """A linked user's confirmed match, the proposal waiting on them, and a listing
    they could claim all land on "/" — no detour through /scrims."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    link_team(C, [TEAM_C], persona="CaptainC")
    with app.test_request_context():
        from app.scrims import accept, create_listing, create_proposal
        accept(B, create_proposal(A, 101, 202, future_iso(2)))  # Alpha vs Bravo, confirmed
        create_proposal(B, 202, 101, future_iso(4))             # Bravo → Alpha, pending
        create_listing(C, 303, future_iso(6))                   # Charlie's open listing
    as_user(client, A)

    body = client.get("/").get_data(as_text=True)
    assert 'data-screen="dashboard"' in body
    assert "Upcoming matches" in body and "Alpha" in body and "Bravo" in body
    assert "Waiting on you" in body and "Accept" in body
    assert "Open listings you can claim" in body and "Charlie" in body
    assert '<time class="ts"' in body            # every stamp goes through local_dt
    assert "Sixes" in body                       # format_labels, not the raw key
    assert 'href="/scrims"' in body              # "View all scrims"
    # servers are a small side box now, not a section under the scrims — and it links
    # to the inventory only, since there is no create-a-server action to offer
    assert "Your servers" in body and '"/servers"' in body
    assert '"/servers/new"' not in body
    assert "Recent servers" not in body


def test_home_can_cancel_and_withdraw_not_just_respond(app, client, link_team):
    """Every scrim the home dashboard shows must be actionable from it. It used to
    render upcoming matches, own listings and outgoing proposals with no way to
    call any of them off, stranding the user on the app's default screen."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.scrims import accept, create_listing, create_proposal
        accept(B, create_proposal(A, 101, 202, future_iso(2)))   # Alpha vs Bravo, confirmed
        outgoing = create_proposal(A, 101, 202, future_iso(5))   # A → B, still pending
        listing = create_listing(A, 101, future_iso(7))          # A's own open listing
    as_user(client, A)

    body = client.get("/").get_data(as_text=True)
    match_id = _confirmed_id(app, A)
    assert f'action="/scrims/{match_id}/cancel"' in body, "no way to cancel a match"
    assert f'action="/scrims/{outgoing}/withdraw"' in body, "no way to withdraw"
    assert f'action="/scrims/listings/{listing}/cancel"' in body, "no way to pull a listing"
    assert "Sent by you" in body


def _confirmed_id(app, steam_id):
    with app.test_request_context():
        from app.scrims import upcoming_confirmed
        return upcoming_confirmed(steam_id)[0]["id"]


def test_scrim_detail_carries_its_own_lifecycle_actions(app, client, link_team):
    """A scrim is actionable from its own page. Reaching it by link and finding no
    way to act sends you hunting through /scrims for the same row."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.scrims import create_listing, create_proposal
        proposal = create_proposal(A, 101, 202, future_iso(3))
        listing = create_listing(A, 101, future_iso(6))

    as_user(client, B)  # recipient sees accept/decline on the proposal's own page
    body = client.get(f"/scrims/{proposal}").get_data(as_text=True)
    assert f'action="/scrims/{proposal}/accept"' in body
    assert f'action="/scrims/{proposal}/decline"' in body

    as_user(client, A)  # proposer sees withdraw there instead, never accept
    body = client.get(f"/scrims/{proposal}").get_data(as_text=True)
    assert f'action="/scrims/{proposal}/withdraw"' in body
    assert f'action="/scrims/{proposal}/accept"' not in body
    # ...and can pull their own listing from its page
    body = client.get(f"/scrims/{listing}").get_data(as_text=True)
    assert f'action="/scrims/listings/{listing}/cancel"' in body

    as_user(client, C)  # an outsider browsing the open listing gets no lifecycle action
    link_team(C, [TEAM_C], persona="CaptainC")
    body = client.get(f"/scrims/{listing}").get_data(as_text=True)
    assert f'action="/scrims/listings/{listing}/cancel"' not in body
    assert f'action="/scrims/{listing}/cancel"' not in body


def test_acting_on_a_scrim_returns_to_the_page_you_acted_from(app, client, link_team):
    """Accept/decline from the home dashboard leaves you on the home dashboard —
    being bounced to /scrims loses your place."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.scrims import create_proposal
        scrim_id = create_proposal(B, 202, 101, future_iso(4))  # Bravo → Alpha, pending
    as_user(client, A)

    assert 'name="next" value="/"' in client.get("/").get_data(as_text=True)
    resp = client.post(f"/scrims/{scrim_id}/accept", data={"next": "/"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")
    assert not resp.headers["Location"].endswith("/scrims")


def test_scrim_action_without_a_next_still_lands_on_the_dashboard(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.scrims import create_proposal
        scrim_id = create_proposal(B, 202, 101, future_iso(4))
    as_user(client, A)

    resp = client.post(f"/scrims/{scrim_id}/decline")
    assert resp.headers["Location"].endswith("/scrims")


def test_forged_next_cannot_redirect_off_site(app, client, link_team):
    """`next` is attacker-reachable, so an off-site target must fall back to the
    scrims dashboard rather than becoming an open redirect."""
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(B, [TEAM_B], persona="CaptainB")
    with app.test_request_context():
        from app.scrims import create_proposal
        scrim_id = create_proposal(B, 202, 101, future_iso(4))
    as_user(client, A)

    resp = client.post(f"/scrims/{scrim_id}/accept", data={"next": "https://evil.example/pwn"})
    assert resp.status_code == 302
    assert "evil.example" not in resp.headers["Location"]
    assert resp.headers["Location"].endswith("/scrims")


def test_home_empty_state_when_nothing_scheduled(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    as_user(client, A)

    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No scrims scheduled yet" in body
    assert '"/scrims/listings/new"' in body  # post a listing
    assert '"/scrims/new"' in body           # or propose a scrim


def test_home_open_listing_preview_is_capped(app, client, link_team):
    link_team(A, [TEAM_A], persona="CaptainA")
    link_team(C, [TEAM_C], persona="CaptainC")
    with app.test_request_context():
        from app.scrims import create_listing
        for day in range(1, 8):  # seven claimable listings
            create_listing(C, 303, future_iso(day))
    as_user(client, A)

    body = client.get("/").get_data(as_text=True)
    assert body.count(">Charlie<") == 5      # preview caps the rows...
    assert "View all scrims" in body         # ...and points at the full page


def test_home_prompts_unlinked_user_to_link_rgl(client, login):
    """The home page is never rgl_link_required: an unlinked user still gets a
    page (not a redirect, not a crash) with the way forward on it."""
    login()
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'data-screen="dashboard"' in body
    assert "RGL" in body and '"/account"' in body
    assert "Upcoming matches" not in body  # no scrim sections without a team


def test_home_anonymous_still_gets_the_landing_page(client):
    body = client.get("/").get_data(as_text=True)
    assert 'data-screen="landing"' in body
    assert "Upcoming matches" not in body
