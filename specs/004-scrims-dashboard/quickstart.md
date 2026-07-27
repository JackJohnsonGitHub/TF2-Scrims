# Quickstart: Scrims Dashboard, Team Rosters & Attendance

Validation guide for feature 004. See [data-model.md](./data-model.md) for tables and
[contracts/dashboard-routes.md](./contracts/dashboard-routes.md) for exact route behavior.

## Prerequisites

- Features 001–003 running locally: `python3 -m flask --app app run` (or the 001 run target).
- A signed-in user with a **linked RGL account and at least one team** (the scrims area keeps
  003's gate — sign in at `/`, link on `/account`).
- Test data: `python3 scripts/seed_demo_team.py` seeds demo opponent teams, an open listing per
  format, and an incoming proposal — everything below is exercisable solo with it.
  (`--clean` removes it all; re-run any time, it's idempotent.)

## Automated validation

```bash
python3 -m pytest tests/ -q                      # full suite
python3 -m pytest tests/unit/test_attendance.py tests/unit/test_rgl_roster.py \
                  tests/unit/test_rgl_season.py tests/unit/test_timefmt.py \
                  tests/integration/test_dashboard.py tests/integration/test_scrim_detail.py \
                  tests/integration/test_propose_discovery.py -q
```

Expected: all green; RGL is mocked (no network). The 003 suites must stay green — the dashboard
merge and expiry filter change routes/queries 003's tests already cover.

## Manual walkthrough

1. **Dashboard (US1)** — Click **Scrims** in the header → one combined two-column page: the main
   column shows open listings from the demo teams (soonest first; compact rows with division and
   notes as sub-lines, no horizontal scrollbar; your own listing flagged as yours with no claim
   button) with **My matches & listings** (upcoming matches + your open listings) beneath; the
   right rail shows **Proposals** with your incoming demo proposal. **＋ New listing** (opens its
   own page) and **Propose a scrim** sit top-right.
   - Old URL check: visiting `/scrims/listings` redirects to `/scrims`.
   - **Viewer-local times (FR-002/FR-009)**: every scrim time — listings table, "My matches &
     listings", the Proposals rail, the detail page — reads as month, day, 12-hour clock and the
     zone *you* are in (`Jul 28 8:52 PM CDT`), never a bare number and never another region's
     clock. Re-run with the machine's timezone changed and the same listing shifts accordingly.
     Then disable JavaScript and reload: the identical times still render, as labelled UTC
     (`Jul 29 1:52 AM UTC`) — a time is never shown without a zone.
2. **Auto-expiry (US1)** — Post a listing ~2 minutes out, wait past its time, reload `/scrims`:
   it's gone from both sections (and its detail page rejects claims). DB row still exists
   (`status` unchanged — read-side expiry).
3. **Roster (US2)** — Click a demo-team listing → detail page shows the listing info and the
   team's RGL roster (leader badge included). Note: seeded demo teams have fake RGL ids, so their
   roster shows the friendly "roster unavailable" notice — that *is* the FR-011 fallback path.
   For a real roster, have a second same-format real team post a listing (or view your own team's
   listing detail).
4. **Claim from detail (US2)** — On a same-format demo listing, claim with your team → confirmed,
   appears in your my-scrims summary.
5. **Attendance (US3)** — Open **your own** team's listing detail → roster renders as the
   tracker (all unconfirmed). As creator, mark several players attending → tally counts toward
   6/7/9 per format. Sign-in as a non-creator teammate (if available) can only change their own
   row. Other teams' members see the roster but **no** attendance section.
6. **Post-claim (US3)** — After the listing is claimed, revisit the same detail URL as the posting
   team: tracker still there and editable until the scheduled time passes, read-only after.
7. **Division browser (US4)** — Open **Propose a scrim**, select one of your teams, and open the
   division selector: it lists only that format's current-season divisions. First visits show
   "Loaded X of Y teams — refresh to load more" while the directory hydrates (~20 teams per
   refresh, live RGL); once warm, pick a division and confirm all its registered teams appear with
   on-platform / "not on the platform yet" labels and your own team unselectable. Propose to an
   off-platform team → normal pending proposal with the "they need to join to respond" note;
   withdraw it. Confirm the quick dropdown still lists only on-platform teams (e.g. the seeded
   demo teams), not the whole league.

## Success criteria spot-checks

| Criterion | Check |
|---|---|
| SC-001 | Header → dashboard is one click; every listing row shows team/format/time; my-scrims on same page. |
| SC-001 (times) | Step 1 — every time reads in the viewer's own zone with the zone named; with JavaScript off the same time renders as labelled UTC. |
| SC-002 | Step 2 — expired listing invisible with no manual action. |
| SC-003 | Top-right actions land on the 003 create/propose flows in one click. |
| SC-004 | Step 3 — roster renders; RGL-down path shows notice, never an error page. |
| SC-005 | Step 5 — marks persist, tally matches, opponents never see attendance. |
| SC-006 | Step 7 — any current-season same-format team findable via the division selector (~30 s once warm); off-platform proposal behaves like any pending proposal. |
