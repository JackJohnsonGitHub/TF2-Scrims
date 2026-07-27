#!/usr/bin/env python3
"""Seed (or remove) a throwaway demo team so scrim flows can be tested solo.

Creates, idempotently:
  - a fake "demo rival" user (never signs in; exists so demo scrims have a creator),
  - one demo team per format the real linked user(s) play (fake RGL team ids in the
    9,99x,xxx range so they can never collide with real RGL ids),
  - one future OPEN LISTING per demo team  -> browse + claim it with your own team,
  - one future PENDING PROPOSAL from each demo team to your same-format team
    -> accept or decline it as yourself.

Your account is deliberately NOT made a member of the demo teams: the propose form
only offers teams you are not on, so this keeps the demo team available as an
opponent for outgoing proposals (withdraw is testable too; accept of incoming is
covered by the seeded proposal).

Usage:
  python3 scripts/seed_demo_team.py            # seed against $DB_PATH (default app.db)
  python3 scripts/seed_demo_team.py --clean    # remove everything it created
  python3 scripts/seed_demo_team.py --db path/to.db

Re-run after using "refresh" on your RGL link if demo data seems stale; safe to run
any number of times.
"""
import argparse
import os
import sqlite3
from datetime import datetime, timedelta, timezone

DEMO_STEAM_ID = "90000000000000001"
DEMO_PERSONA = "Demo Rival Captain"
# Fake RGL team ids, far above real ones (currently 4-5 digits).
DEMO_TEAMS = {
    "sixes": (9990001, "TMP Demo Team", "TMP", "RGL-Demo"),
    "highlander": (9990002, "TMP Demo Team HL", "TMPHL", "RGL-Demo"),
    "prolander": (9990003, "TMP Demo Team PL", "TMPPL", "RGL-Demo"),
}
DEMO_TEAM_IDS = tuple(t[0] for t in DEMO_TEAMS.values())


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def in_days(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec="seconds")


def clean(db: sqlite3.Connection) -> None:
    ph = ",".join("?" * len(DEMO_TEAM_IDS))
    n = db.execute(
        f"""DELETE FROM scrims WHERE proposer_team_id IN ({ph})
            OR opponent_team_id IN ({ph}) OR created_by = ?""",
        (*DEMO_TEAM_IDS, *DEMO_TEAM_IDS, DEMO_STEAM_ID),
    ).rowcount
    db.execute(
        f"DELETE FROM rgl_memberships WHERE rgl_team_id IN ({ph}) OR steam_id = ?",
        (*DEMO_TEAM_IDS, DEMO_STEAM_ID),
    )
    db.execute(f"DELETE FROM rgl_teams WHERE rgl_team_id IN ({ph})", DEMO_TEAM_IDS)
    db.execute("DELETE FROM users WHERE steam_id = ?", (DEMO_STEAM_ID,))
    db.commit()
    print(f"Removed demo user, demo teams, and {n} demo scrim(s).")


def seed(db: sqlite3.Connection) -> None:
    now = utc_now()

    # Formats the real linked users actually play — only seed rivals they can face.
    real_formats = {
        r["format"]
        for r in db.execute(
            """SELECT DISTINCT t.format FROM rgl_teams t
               JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
               WHERE m.steam_id != ?""",
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
           VALUES (?, ?, ?, ?)
           ON CONFLICT(steam_id) DO UPDATE SET persona_name = excluded.persona_name""",
        (DEMO_STEAM_ID, DEMO_PERSONA, now, now),
    )

    for fmt in sorted(real_formats & DEMO_TEAMS.keys()):
        team_id, name, tag, division = DEMO_TEAMS[fmt]
        db.execute(
            """INSERT INTO rgl_teams (rgl_team_id, name, tag, format, division_name,
                                      season_id, updated_at)
               VALUES (?, ?, ?, ?, ?, NULL, ?)
               ON CONFLICT(rgl_team_id) DO UPDATE SET name = excluded.name,
                   tag = excluded.tag, division_name = excluded.division_name,
                   updated_at = excluded.updated_at""",
            (team_id, name, tag, fmt, division, now),
        )
        db.execute(
            "INSERT OR IGNORE INTO rgl_memberships (steam_id, rgl_team_id) VALUES (?, ?)",
            (DEMO_STEAM_ID, team_id),
        )

        # One future open listing from the demo team, claimable by a real team.
        have_listing = db.execute(
            """SELECT 1 FROM scrims WHERE proposer_team_id = ? AND origin = 'listing'
               AND status = 'open' AND scheduled_at > ?""",
            (team_id, now),
        ).fetchone()
        if not have_listing:
            db.execute(
                """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                       opponent_team_id, status, created_by, created_at,
                                       updated_at, notes)
                   VALUES (?, ?, 'listing', ?, NULL, 'open', ?, ?, ?, ?)""",
                (fmt, in_days(2), team_id, DEMO_STEAM_ID, now, now,
                 "Demo listing — claim me to test the flow."),
            )
            print(f"[{fmt}] open listing posted by {name} (~2 days out)")

        # One pending proposal from the demo team to each real same-format team,
        # so accept/decline is testable without a second account.
        for real in db.execute(
            """SELECT DISTINCT t.rgl_team_id, t.name FROM rgl_teams t
               JOIN rgl_memberships m ON m.rgl_team_id = t.rgl_team_id
               WHERE t.format = ? AND m.steam_id != ?""",
            (fmt, DEMO_STEAM_ID),
        ).fetchall():
            have_proposal = db.execute(
                """SELECT 1 FROM scrims WHERE proposer_team_id = ? AND opponent_team_id = ?
                   AND status = 'pending' AND scheduled_at > ?""",
                (team_id, real["rgl_team_id"], now),
            ).fetchone()
            if not have_proposal:
                db.execute(
                    """INSERT INTO scrims (format, scheduled_at, origin, proposer_team_id,
                                           opponent_team_id, status, created_by, created_at,
                                           updated_at, notes)
                       VALUES (?, ?, 'proposal', ?, ?, 'pending', ?, ?, ?, ?)""",
                    (fmt, in_days(3), team_id, real["rgl_team_id"], DEMO_STEAM_ID,
                     now, now, "Demo proposal — accept or decline me."),
                )
                print(f"[{fmt}] pending proposal: {name} -> {real['name']} (~3 days out)")

    db.commit()
    print("\nSeeded. You can now test:")
    print("  - /scrims      : one dashboard — claim the demo team's open listing with")
    print("                   your team, and accept/decline its pending proposal")
    print("  - /scrims/<id> : listing detail + team roster (demo teams carry fake RGL")
    print("                   ids, so theirs shows the 'roster unavailable' notice —")
    print("                   that is the intended fallback); your own team's listing")
    print("                   also shows the attendance tracker")
    print("  - /scrims/new  : propose to the demo team, then withdraw it")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=os.environ.get("DB_PATH", "app.db"))
    parser.add_argument("--clean", action="store_true",
                        help="remove all demo data instead of seeding")
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"Database not found: {args.db} (run the app once first)")
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    try:
        clean(db) if args.clean else seed(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
