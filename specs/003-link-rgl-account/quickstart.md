# Quickstart & Validation: Link RGL Account & Schedule Scrims

Runnable checks. Route/data details live in [contracts/](./contracts/) and [data-model.md](./data-model.md).

## Prerequisites

- The app from features 001 + 002 (signed-in Steam identity).
- Outbound HTTPS to `api.rgl.gg` (public, **no key**) for real linking.
- Two RGL-linked test accounts on same-format teams to exercise scheduling end-to-end (or use the
  mocked tests).

## 1. Link RGL (US1)

```bash
. .venv/bin/activate
uv pip install -r requirements.txt   # no new deps beyond 002
# run as in 002 (APP_SECRET_KEY etc.)
flask --app app run --debug
```

**Expected**

- On `/account`, a signed-in user sees "Link RGL account"; clicking it fetches their profile **by their
  SteamID** (no ID entry) and shows their profile name + current team(s) grouped by format, with
  division/season and any verified/banned/probation badge.
- A user with no RGL profile sees "no RGL profile found"; a profile with no team shows "no current
  team"; if RGL is down, a retry message shows and the page still works.
- Refresh updates the teams; unlink removes the link (status → not linked).

## 2. Schedule a scrim — directed propose → accept (US2)

- As team A, open `/scrims/new`, pick your team, an opponent team of the **same format**, and a future
  date/time → the proposal shows as **pending** (outgoing for A, incoming for B).
- As a **member of team B**, accept it → the scrim is **confirmed** and appears as upcoming for both.
- Decline / withdraw a pending proposal → no match; it closes.
- Try proposing to a different-format team, your own team, or a past time → rejected with a message.

## 3. Schedule a scrim — open listing → claim (US3)

- As team A, post an open listing (your team, format, future time) → appears under `/scrims/listings`.
- As a same-format team B, claim it → **confirmed** between A and B; the listing leaves the open list.
- Two teams claiming the same listing → first wins; the second sees "no longer available".
- Owner cancels an unclaimed listing → removed.

## 4. Automated tests (RGL mocked)

```bash
python -m pytest -q
```

**Expected**: `tests/unit/test_rgl.py` (profile parsing, no-profile/no-team/unavailable fallbacks),
`tests/unit/test_scrims.py` (state transitions, same-format, past-date/self rejects),
`tests/integration/test_rgl_link.py` (link/refresh/unlink + gating), `tests/integration/test_scrims.py`
(propose→accept/decline, listing→claim first-wins, cancel, cross-team authority blocked). All prior
001/002 tests still pass.

## 5. Guards & non-goals

- Anonymous or RGL-unlinked access to `/rgl/*` or `/scrims/*` → redirected (login / link-required).
- A user cannot act for a team they're not on (server rejects).
- **No server is created by any scheduling action** — confirm no provisioning side effects.

## Success-criteria mapping

| Criterion | Validated by |
|---|---|
| SC-001 link < 10s, no manual entry | Step 1 |
| SC-002 profile/teams match, persist, refresh/unlink | Step 1 |
| SC-003 propose→accept confirmed < 2 min | Step 2 |
| SC-004 both paths produce a confirmed scrim | Steps 2 + 3 |
| SC-005 same-format only | Steps 2 + 3 + tests |
| SC-006 act only for your team | test_scrims authority |
| SC-007 no server provisioning | Step 5 + tests |
| SC-008 graceful no-profile/no-team/unavailable | Step 1 + tests |
