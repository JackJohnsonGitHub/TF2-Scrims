#!/usr/bin/env python3
"""Seed (or remove) a throwaway demo team so scrim flows can be tested solo.

Creates, idempotently:
  - a fake "demo rival" user (never signs in; exists so demo scrims have a creator),
  - one demo team per format the real linked user(s) play (fake RGL team ids in the
    9,99x,xxx range so they can never collide with real RGL ids),
  - a fake ROSTER for each demo team  -> the roster panel on a listing's detail page,
  - one future OPEN LISTING per demo team  -> browse + claim it with your own team,
  - one future PENDING PROPOSAL from each demo team to your same-format team
    -> accept or decline it as yourself,
  - one future OPEN LISTING posted by YOUR OWN team  -> the attendance tracker.

Your account is deliberately NOT made a member of the demo teams: the propose form
only offers teams you are not on, so this keeps the demo team available as an
opponent for outgoing proposals (withdraw is testable too; accept of incoming is
covered by the seeded proposal).

That is also why the demo teams' own listings can never show you the attendance
tracker — it renders only for members of the team that POSTED the listing — and why
the last item above exists. Its roster is your team's real one from RGL, not a fake:
seeding fake players onto a real team would be erased the next time RGL is polled.

This is the documented way to make an empty store a usable starting point (FR-006), and
it reaches the store through `app/db.py` like every other process does (FR-023) — no
driver connection of its own, so connection settings and integrity guarantees cannot
drift between it and the app.

Usage:
  python3 scripts/seed_demo_team.py            # seed against $DATABASE_URL
  python3 scripts/seed_demo_team.py --clean    # remove everything it created
  python3 scripts/seed_demo_team.py --dsn postgresql://user:pass@host:5432/db

Re-run after using "refresh" on your RGL link if demo data seems stale; safe to run
any number of times.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import psycopg

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEMO_STEAM_ID = "90000000000000001"
DEMO_PERSONA = "Demo Rival Captain"
# Fake RGL team ids, far above real ones (currently 4-5 digits).
DEMO_TEAMS = {
    "sixes": (9990001, "TMP Demo Team", "TMP", "RGL-Demo"),
    "highlander": (9990002, "TMP Demo Team HL", "TMPHL", "RGL-Demo"),
    "prolander": (9990003, "TMP Demo Team PL", "TMPPL", "RGL-Demo"),
}
DEMO_TEAM_IDS = tuple(t[0] for t in DEMO_TEAMS.values())

# Fake rosters for the demo teams, so a demo listing's detail page shows a real
# roster panel instead of the "roster unavailable" notice. Each is the format
# minimum (attendance.FORMAT_SIZES) plus the captain as a sub, so the attendance
# counter can be driven both under and over the required count.
#
# ensure_roster() only overwrites a cached roster on a SUCCESSFUL RGL fetch, and
# these fake team ids always 404, so seeded rosters survive indefinitely — the
# stamp below just keeps it from retrying RGL more than once an hour.
DEMO_ROSTER_NAMES = {
    "sixes": ["scoutzilla", "bonkbandit", "roamerrr", "pocketwatch",
              "stickysitch", "nevercharged"],
    "highlander": ["scoutzilla", "roamerrr", "flamefan", "stickysitch",
                   "sandvichgod", "wranglerman", "nevercharged", "quickscoped",
                   "backstabbath"],
    "prolander": ["scoutzilla", "roamerrr", "stickysitch", "sandvichgod",
                  "wranglerman", "nevercharged", "quickscoped"],
}
# Sequence per format, used to build unique fake SteamID64s (17 digits, 9-prefixed
# like DEMO_STEAM_ID — real ids start 7656119…, so these can never collide).
DEMO_ROSTER_SEQ = {"sixes": 1, "highlander": 2, "prolander": 3}

# Marks the listing seeded on the REAL user's own team. Attendance is posting-team
# only, so a demo team's listing can never show the tracker to you — this one can.
# The sentinel is how --clean finds it again (it is not owned by a demo id).
ATTENDANCE_NOTE = "Demo listing — your own team's, so the attendance tracker shows."


def roster_steam_id(fmt: str, index: int) -> str:
    """Deterministic fake SteamID64 for demo roster player `index` in `fmt`."""
    return f"9000000000000{DEMO_ROSTER_SEQ[fmt]:02d}{index:02d}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def in_days(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def seed_roster(db: psycopg.Connection, team_id: int, fmt: str, now: str) -> int:
    """Replace a demo team's cached roster with the fake one for its format. The
    demo captain leads; the rest are roster-only players with no app account (which
    is realistic — most RGL players on an opposing roster will never sign in here,
    and the attendance creator path is specified to handle exactly that)."""
    db.execute("DELETE FROM rgl_rosters WHERE rgl_team_id = %s", (team_id,))
    db.execute(
        """INSERT INTO rgl_rosters (rgl_team_id, steam_id, name, is_leader)
           VALUES (%s, %s, %s, 1)""",
        (team_id, DEMO_STEAM_ID, DEMO_PERSONA),
    )
    for index, name in enumerate(DEMO_ROSTER_NAMES[fmt], start=1):
        db.execute(
            """INSERT INTO rgl_rosters (rgl_team_id, steam_id, name, is_leader)
               VALUES (%s, %s, %s, 0)""",
            (team_id, roster_steam_id(fmt, index), name),
        )
    # Stamping the fetch keeps ensure_roster from calling RGL for an id it can
    # never resolve; a stale stamp is harmless either way (the 404 leaves the
    # cache untouched), this just keeps the log quiet.
    db.execute(
        """INSERT INTO rgl_roster_meta (rgl_team_id, fetched_at) VALUES (%s, %s)
           ON CONFLICT(rgl_team_id) DO UPDATE SET fetched_at = excluded.fetched_at""",
        (team_id, now),
    )
    return len(DEMO_ROSTER_NAMES[fmt]) + 1


def seed_servers(db: psycopg.Connection, team_id: int, name: str, now: str) -> int:
    """Two demo servers for a demo team — one running, one stopped.

    They belong to the demo rival, not to you, which is the point: the access rule
    (own it, or be on its team) gets exercised by the sample data rather than around
    it. They are also flagged `demo` so no screen can pass them off as real.
    """
    existing = db.execute(
        "SELECT COUNT(*) AS c FROM servers WHERE team_id = %s AND demo = 1", (team_id,)
    ).fetchone()["c"]
    if existing:
        return 0
    rows = [
        (f"{name} — match server", "cp_process_final", 24, "running",
         "10.0.0.5:27015", 12),
        (f"{name} — jump practice", "jump_academy_b4", 8, "stopped", None, None),
    ]
    for srv_name, map_name, slots, state, address, players in rows:
        db.execute(
            """INSERT INTO servers (owner_steam_id, team_id, state, name, map,
                                    max_slots, address, players, demo,
                                    stopped_reason, created_at, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s)""",
            (DEMO_STEAM_ID, team_id, state, srv_name, map_name, slots, address,
             players, None if state == "running" else "time_expired", now, now),
        )
    return len(rows)


def clean(db: psycopg.Connection) -> None:
    ph = ",".join(["%s"] * len(DEMO_TEAM_IDS))
    # Servers before scrims: a per-scrim server references its scrim, and foreign keys
    # are enforced as of feature 005 — deleting the scrim first would now fail.
    db.execute(
        f"""DELETE FROM credit_ledger WHERE server_id IN (
                SELECT id FROM servers WHERE team_id IN ({ph})
                OR owner_steam_id = %s)""",
        (*DEMO_TEAM_IDS, DEMO_STEAM_ID),
    )
    db.execute(
        f"DELETE FROM servers WHERE team_id IN ({ph}) OR owner_steam_id = %s",
        (*DEMO_TEAM_IDS, DEMO_STEAM_ID),
    )
    db.execute(
        f"""DELETE FROM credit_ledger WHERE scrim_id IN (
                SELECT id FROM scrims WHERE proposer_team_id IN ({ph})
                OR opponent_team_id IN ({ph}) OR created_by = %s OR notes = %s)""",
        (*DEMO_TEAM_IDS, *DEMO_TEAM_IDS, DEMO_STEAM_ID, ATTENDANCE_NOTE),
    )
    db.execute("DELETE FROM credit_ledger WHERE steam_id = %s", (DEMO_STEAM_ID,))
    db.execute("DELETE FROM payments WHERE steam_id = %s", (DEMO_STEAM_ID,))
    db.execute("DELETE FROM steam_trade_links WHERE steam_id = %s", (DEMO_STEAM_ID,))
    # Attendance rows first — no ON DELETE CASCADE, so they would outlive their
    # scrim and reappear against a re-seeded one with the same id.
    db.execute(
        f"""DELETE FROM scrim_attendance WHERE scrim_id IN (
                SELECT id FROM scrims WHERE proposer_team_id IN ({ph})
                OR opponent_team_id IN ({ph}) OR created_by = %s OR notes = %s)""",
        (*DEMO_TEAM_IDS, *DEMO_TEAM_IDS, DEMO_STEAM_ID, ATTENDANCE_NOTE),
    )
    n = db.execute(
        f"""DELETE FROM scrims WHERE proposer_team_id IN ({ph})
            OR opponent_team_id IN ({ph}) OR created_by = %s OR notes = %s""",
        (*DEMO_TEAM_IDS, *DEMO_TEAM_IDS, DEMO_STEAM_ID, ATTENDANCE_NOTE),
    ).rowcount
    db.execute(
        f"DELETE FROM rgl_memberships WHERE rgl_team_id IN ({ph}) OR steam_id = %s",
        (*DEMO_TEAM_IDS, DEMO_STEAM_ID),
    )
    db.execute(f"DELETE FROM rgl_rosters WHERE rgl_team_id IN ({ph})", DEMO_TEAM_IDS)
    db.execute(f"DELETE FROM rgl_roster_meta WHERE rgl_team_id IN ({ph})", DEMO_TEAM_IDS)
    db.execute(f"DELETE FROM rgl_teams WHERE rgl_team_id IN ({ph})", DEMO_TEAM_IDS)
    db.execute("DELETE FROM users WHERE steam_id = %s", (DEMO_STEAM_ID,))
    db.commit()
    print(f"Removed demo user, demo teams, demo rosters, demo servers, "
          f"credits and {n} demo scrim(s).")


def seed(db: psycopg.Connection) -> None:
    now = utc_now()

    # Formats the real linked users actually play — only seed rivals they can face.
    real_formats = {
        r["format"]
        for r in db.execute(
            """SELECT DISTINCT t.format FROM rgl_teams t
               JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
               WHERE m.steam_id != %s""",
            (DEMO_STEAM_ID,),
        )
    }
    if not real_formats:
        raise SystemExit(
            "No linked user with a team found — sign in and link your RGL account "
            "first, then re-run this script."
        )

    db.execute(
        """INSERT INTO users (steam_id, persona_name, created_at, last_login_at)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT(steam_id) DO UPDATE SET persona_name = excluded.persona_name""",
        (DEMO_STEAM_ID, DEMO_PERSONA, now, now),
    )

    for fmt in sorted(real_formats & DEMO_TEAMS.keys()):
        team_id, name, tag, division = DEMO_TEAMS[fmt]
        db.execute(
            """INSERT INTO rgl_teams (rgl_team_id, name, tag, format, division_name,
                                      season_id, updated_at)
               VALUES (%s, %s, %s, %s, %s, NULL, %s)
               ON CONFLICT(rgl_team_id) DO UPDATE SET name = excluded.name,
                   tag = excluded.tag, division_name = excluded.division_name,
                   updated_at = excluded.updated_at""",
            (team_id, name, tag, fmt, division, now),
        )
        db.execute(
            "INSERT INTO rgl_memberships (steam_id, rgl_team_id) VALUES (%s, %s)"
            " ON CONFLICT DO NOTHING",
            (DEMO_STEAM_ID, team_id),
        )
        size = seed_roster(db, team_id, fmt, now)
        print(f"[{fmt}] roster seeded for {name} ({size} players)")
        made = seed_servers(db, team_id, name, now)
        if made:
            print(f"[{fmt}] {made} demo server(s) seeded for {name}")

        # One future open listing from the demo team, claimable by a real team.
        have_listing = db.execute(
            """SELECT 1 FROM scrims WHERE proposer_team_id = %s AND origin = 'listing'
               AND status = 'open' AND scheduled_at > %s""",
            (team_id, now),
        ).fetchone()
        if not have_listing:
            db.execute(
                """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                       opponent_team_id, status, created_by, created_at,
                                       updated_at, notes)
                   VALUES (%s, %s, 'listing', %s, NULL, 'open', %s, %s, %s, %s)""",
                (fmt, in_days(2), team_id, DEMO_STEAM_ID, now, now,
                 "Demo listing — claim me to test the flow."),
            )
            print(f"[{fmt}] open listing posted by {name} (~2 days out)")

        # One pending proposal from the demo team to each real same-format team,
        # so accept/decline is testable without a second account.
        # MIN(steam_id) picks one real member to own the seeded own-team listing
        # below; on a single-account deploy that is simply you.
        for real in db.execute(
            """SELECT t.rgl_team_id, t.name, MIN(m.steam_id) AS member_steam_id
               FROM rgl_teams t
               JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
               WHERE t.format = %s AND m.steam_id != %s
               GROUP BY t.rgl_team_id, t.name""",
            (fmt, DEMO_STEAM_ID),
        ).fetchall():
            have_proposal = db.execute(
                """SELECT 1 FROM scrims WHERE proposer_team_id = %s AND opponent_team_id = %s
                   AND status = 'pending' AND scheduled_at > %s""",
                (team_id, real["rgl_team_id"], now),
            ).fetchone()
            if not have_proposal:
                db.execute(
                    """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                           opponent_team_id, status, created_by, created_at,
                                           updated_at, notes)
                       VALUES (%s, %s, 'proposal', %s, %s, 'pending', %s, %s, %s, %s)""",
                    (fmt, in_days(3), team_id, real["rgl_team_id"], DEMO_STEAM_ID,
                     now, now, "Demo proposal — accept or decline me."),
                )
                print(f"[{fmt}] pending proposal: {name} -> {real['name']} (~3 days out)")

            # An open listing posted by the REAL team, created by one of its own
            # members. Attendance renders only to members of the posting team, so
            # this — not the demo team's listing — is where the tracker appears.
            # Created by that member so they also get the mark-anyone creator path.
            have_own = db.execute(
                "SELECT 1 FROM scrims WHERE proposer_team_id = %s AND notes = %s",
                (real["rgl_team_id"], ATTENDANCE_NOTE),
            ).fetchone()
            if not have_own:
                db.execute(
                    """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                           opponent_team_id, status, created_by, created_at,
                                           updated_at, notes)
                       VALUES (%s, %s, 'listing', %s, NULL, 'open', %s, %s, %s, %s)""",
                    (fmt, in_days(4), real["rgl_team_id"], real["member_steam_id"],
                     now, now, ATTENDANCE_NOTE),
                )
                print(f"[{fmt}] own-team listing posted by {real['name']} "
                      f"(~4 days out) — attendance tracker lives here")

    db.commit()
    print("\nSeeded. You can now test:")
    print("  - /scrims      : one dashboard — claim the demo team's open listing with")
    print("                   your team, and accept/decline its pending proposal")
    print("  - /scrims/<id> : listing detail + the posting team's roster — the demo")
    print("                   teams now carry a fake one, so the panel renders")
    print("  - the own-team listing above: the attendance tracker. You created it, so")
    print("                   you can mark every player, not just yourself.")
    print("  - /scrims/new  : propose to the demo team, then withdraw it")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", default=None,
                        help="store connection string; defaults to $DATABASE_URL")
    parser.add_argument("--clean", action="store_true",
                        help="remove all demo data instead of seeding")
    args = parser.parse_args()

    # Through the shared access path (FR-023): build the app, then borrow its connection.
    # Building it also brings the store to the current schema, so seeding works against a
    # store that has never been used — which is what makes an empty store a usable
    # starting point rather than a dead end (FR-006).
    from app import create_app
    from app.config import Config
    from app.db import close_db, get_db

    class SeedConfig(Config):
        DATABASE_URL = args.dsn or Config.DATABASE_URL

    try:
        app = create_app(SeedConfig)
    except psycopg.OperationalError as exc:
        raise SystemExit(
            f"Cannot reach the store: {exc}\n"
            "Start one, or pass --dsn. See README, 'Running the app'."
        )

    with app.app_context():
        try:
            clean(get_db()) if args.clean else seed(get_db())
        finally:
            close_db()


if __name__ == "__main__":
    main()
