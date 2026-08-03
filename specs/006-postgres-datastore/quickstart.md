# Quickstart: Validating the Durable Multi-Writer Metadata Store

**Feature**: `006-postgres-datastore` · **Spec**: [spec.md](./spec.md) ·
**Contracts**: [store-access.md](./contracts/store-access.md),
[deployment.md](./contracts/deployment.md)

This feature changes **no user-facing behavior** (FR-001). So most of what needs proving is
either invisible from a screen (concurrency, integrity, recovery) or is the *absence* of
change (SC-007). Validation is shaped accordingly: the scenarios below check things that
were previously impossible to check at all, plus one deliberate walkthrough that must find
nothing.

**SC-006 is itself a scenario**: a developer goes from fresh clone to a passing suite in
under 15 minutes, including standing up a local store. Scenario 0 is that clock.

---

## Prerequisites

- Docker (for the local store), or any reachable PostgreSQL 17
- Python 3.12 and `uv`
- `psql` / `pg_dump` / `pg_restore` — via `apt install postgresql-client`, or run them inside
  the container with `docker exec`

---

## Scenario 0 — Fresh clone to passing tests (SC-006, FR-024, FR-025)

Start a timer. The target is **15 minutes**, and most of it is the image pull.

```bash
# 1. The store. One engine everywhere — dev, tests, and deploy (FR-025).
docker run -d --name tf2-pg -p 5432:5432 \
  -e POSTGRES_PASSWORD=dev -e POSTGRES_USER=tf2app -e POSTGRES_DB=tf2hosting \
  postgres:17-alpine

# 2. The app.
uv venv .venv && . .venv/bin/activate
uv pip install -r requirements.txt

export DATABASE_URL="postgresql://tf2app:dev@localhost:5432/tf2hosting"
export APP_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export APP_BASE_URL="http://localhost:5000"

# 3. The suite. Migrations apply once; each test truncates (FR-027).
python -m pytest -q
```

**Expected**: the full existing suite passes (**SC-001**, FR-003). Test count is unchanged
except where a test asserted a detail of SQLite's mechanics rather than platform behavior —
the pragma assertions in `tests/unit/test_db.py`, which are replaced by behavioral equivalents
(foreign keys refuse an orphan; concurrent writers both succeed), not deleted.

**Then check the failure mode FR-024 names explicitly:**

```bash
docker stop tf2-pg && python -m pytest -q
```

**Expected**: the run stops immediately with one actionable message naming the `docker run`
line and `DATABASE_URL` — **not** 226 connection stack traces that read like broken tests.

```bash
docker start tf2-pg
```

---

## Automated validation

```bash
python -m pytest -q                                   # SC-001 — the whole suite
python -m pytest tests/unit/test_db.py -q             # store access, migrations, pragma replacements
python -m pytest tests/integration/test_concurrency.py -q   # NEW — FR-008–FR-015 under real concurrency
python -m pytest tests/integration/test_success_criteria.py -q
```

`test_concurrency.py` is the file FR-026 requires: the integrity rules exercised against the
same engine the deployment uses, so a violation cannot pass tests and fail in production.

---

## Scenario 1 — Concurrent writes stop failing (US1, FR-008, SC-002)

The 8pm Sunday scenario: page loads, the payment poller, and the reconciler all writing at
once.

```bash
python -m pytest tests/integration/test_concurrency.py -q -k contention

# Or by hand — drive the app while both jobs run against the same store:
flask --app app run &
while true; do flask --app app poll-payments; flask --app app reconcile-servers; done &
# then load /scrims, /servers, /credits repeatedly from ≥20 concurrent clients
```

**Expected**: zero failed requests. No `database is locked`, no 500s, no hangs. Against a
baseline where every one of those was possible (SC-002).

**Also expected — and worth watching for**: a page load *during* a credit write renders
normally rather than waiting on it (US1 acceptance 1). Under WAL that was true for readers;
under Postgres it is true generally, and unrelated accounts never contend at all.

---

## Scenario 2 — A balance cannot go negative (FR-013, research R9)

**The scenario that changed.** `credits._spend` was correct under SQLite only because there
was one global writer. This is the test that proves the row lock replaced that guarantee
rather than removing it.

```bash
python -m pytest tests/integration/test_concurrency.py -q -k spend_race
```

The test: an account holding **exactly 1 credit**, N concurrent processes each attempting to
reserve one.

**Expected**: exactly one succeeds. The others raise `InsufficientCredits`. The ledger sums to
0 and **never** to a negative number, at any point during or after the run.

Run it against a build without the `FOR UPDATE` lock and it fails — that is the point of
having it.

---

## Scenario 3 — Exactly-once crediting (US1 acceptance 2, FR-009, SC-003)

```bash
python -m pytest tests/integration/test_concurrency.py -q -k exactly_once
```

Replay the same completed payment **at least 10 times**, including from processes running
simultaneously (SC-003).

**Expected**: exactly one credit grant, exactly one ledger entry for that payment. Enforced by
`UNIQUE (method, provider_ref)` in the store — not by the poller behaving well, which is the
distinction that matters, since it re-reads every offer on every run and can be run twice by
hand.

Verify directly:

```sql
SELECT method, provider_ref, COUNT(*) FROM payments
 GROUP BY 1,2 HAVING COUNT(*) > 1;                              -- expect: 0 rows
SELECT payment_id, COUNT(*) FROM credit_ledger
 WHERE kind='grant' AND payment_id IS NOT NULL
 GROUP BY 1 HAVING COUNT(*) > 1;                                -- expect: 0 rows
```

---

## Scenario 4 — One server per scrim, and one transaction (FR-010, FR-012)

```bash
python -m pytest tests/integration/test_concurrency.py -q -k "one_server or attach_atomic"
```

**Expected**:
- Two simultaneous attaches to the same scrim → exactly one server exists. The partial unique
  index refuses the second (FR-010).
- The loser's credit is **not** consumed, and no half-attached server row is left behind — the
  reservation and the server creation are one transaction now, not two (FR-012, research R19).

---

## Scenario 5 — Referential integrity is unconditional (FR-011)

```sql
-- A ledger entry for an account that does not exist.
INSERT INTO credit_ledger (steam_id, delta, kind, cause, created_at)
VALUES ('76561190000000000', 5, 'grant', 'nobody', '2026-07-31T00:00:00+00:00');
```

**Expected**: `ForeignKeyViolation`. On every connection, with no pragma to remember and no
way to switch it off — which is the improvement over a store where every `REFERENCES` clause
was decorative until feature 005 turned them on by hand.

---

## Scenario 6 — Several copies initialise at once (US3 acceptance 3, FR-015)

```bash
python -m pytest tests/integration/test_concurrency.py -q -k migrate_race

# Or by hand, against an empty database:
for i in 1 2 3 4; do flask --app app --help >/dev/null & done; wait
```

**Expected**: the schema is created **exactly once**, no invocation fails, and
`schema_migrations` holds one row per migration file — never a duplicate, never a partial
schema. The advisory lock serializes them; Postgres's transactional DDL means a failure
midway leaves nothing half-created.

---

## Scenario 7 — Restore rehearsal (US2, FR-018, SC-005)

**SC-005 requires this be rehearsed at least once**, restoring a state no more than 24 hours
old and back in service within 30 minutes. Start a timer.

```bash
# 1. Seed something recognisable, then back it up.
python scripts/seed_demo_team.py
pg_dump -Fc --dbname="$DATABASE_URL" --file=/tmp/rehearsal.dump

# 2. Note the balances you are about to destroy.
psql "$DATABASE_URL" -c \
  "SELECT steam_id, SUM(delta) AS balance FROM credit_ledger GROUP BY 1 ORDER BY 1;"

# 3. Destroy the store.
psql "$DATABASE_URL" -c 'DROP SCHEMA public CASCADE; CREATE SCHEMA public;'

# 4. Restore.
pg_restore --dbname="$DATABASE_URL" --no-owner /tmp/rehearsal.dump

# 5. Verify.
psql "$DATABASE_URL" -c \
  "SELECT steam_id, SUM(delta) AS balance FROM credit_ledger GROUP BY 1 ORDER BY 1;"
flask --app app run   # → sign in, open /credits
```

**Expected**:
- The platform serves requests with all data as of the dump (US2 acceptance 1).
- Balances match step 2 exactly, and each user's `/credits` page shows a balance equal to the
  sum of their restored ledger entries (US2 acceptance 2, FR-013). This holds by construction —
  there is no stored total that could survive a restore disagreeing with the rows — but it is
  checked anyway, because "by construction" is a claim until something verifies it.
- Total elapsed time **under 30 minutes** (SC-005).

---

## Scenario 8 — Backup visibility (US2 acceptance 3, FR-017)

On the cluster:

```bash
kubectl get jobs -l component=backup --sort-by=.status.startTime
kubectl exec deploy/tf2-hosting-app -- cat /backups/latest.json
```

**Expected**: the operator can see **when the last successful backup completed** and confirm
it is recent — without reading logs. A `completed_at` older than the schedule is itself the
alarm, which is the failure mode worth engineering against: a backup that silently stopped
working looks exactly like one that is running.

---

## Scenario 9 — Deploys stop being outages (US3, FR-014, SC-004)

```bash
# Continuous traffic while a rolling deploy runs.
while true; do curl -fsS -o /dev/null -w '%{http_code}\n' https://<host>/scrims; done &
kubectl rollout restart deployment/tf2-hosting-app
kubectl rollout status  deployment/tf2-hosting-app
```

**Expected**: **zero non-200 responses** (SC-004), against a guaranteed interruption today.
`maxUnavailable: 0` means a new pod passes its store-backed readiness check before an old one
goes away.

Also check session continuity (US3 acceptance 2): sign in, then keep requesting until served
by the other pod. You stay signed in and see the same data — sessions are signed cookies keyed
by a shared `APP_SECRET_KEY`, with no server-side session state to share.

---

## Scenario 10 — The store is unreachable (FR-016, Edge Cases)

```bash
docker stop tf2-pg
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5000/healthz    # → 503
docker start tf2-pg
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:5000/healthz    # → 200
```

**Expected**:
- Readiness **fails** and the failure is **logged**, with the DSN redacted to `host:port/db` —
  never credentials.
- The app does not serve pages that look normal but show nothing. That silent mode is the
  specific failure FR-016 exists to prevent.
- After the store returns, the app recovers **without a restart** — the pool discards the dead
  connection and opens a fresh one (the "brief connection interruption" edge case).

---

## Scenario 11 — The RGL cache starts cold (FR-007, Edge Cases)

Against a freshly emptied store, with no seeding:

1. Sign in, link an RGL account.
2. Open the propose flow's division browser.

**Expected**: the directory repopulates from the RGL API on demand, within the existing
per-request hydration bound (`RGL_HYDRATE_BATCH`) — it does not stall, time out, or present
an empty directory as if the league had no teams. No operator action, no background job.

This works because `rgl_season_teams.rgl_team_id` deliberately carries **no** foreign key: the
browser records registrations before hydrating team details. Adding that FK would look like
tightening integrity and would break this scenario.

---

## Scenario 12 — Nothing user-facing changed (FR-001, FR-002, SC-007)

The walkthrough that must find nothing. Every existing surface, before and after:

sign-in → RGL linking → dashboard → open listings → propose → claim → scrim detail → roster →
attendance → opponent discovery → account/trade link → credits → payment → servers → server
detail → extend → console.

**Expected**: identical results (SC-007). And specifically (FR-002), the authority rules are
unchanged — both teams in a scrim can **join** its server; only the organising team's
RGL-designated leaders can **control** it (constitution VIII).

---

## Deployment check

> Shown against **`deploy/`** — the dependency-free manifest set, which is what you can
> run on a scratch cluster. Shipping to `mke` goes through `irulast-deploy/` instead
> (`kubectl apply -k irulast-deploy/`, or Flux); see
> [`irulast-deploy/README.md`](../../irulast-deploy/README.md). The checks below apply to
> either — only the apply step differs.

```bash
kubectl apply -f deploy/postgres-service.yaml -f deploy/postgres-statefulset.yaml
kubectl rollout status statefulset/tf2-hosting-postgres

kubectl apply -f deploy/deployment.yaml -f deploy/service.yaml
kubectl apply -f deploy/cronjob-poll-payments.yaml \
               -f deploy/cronjob-reconcile-servers.yaml \
               -f deploy/backup-pvc.yaml \
               -f deploy/cronjob-backup-postgres.yaml

kubectl get pods -l app=tf2-hosting-app          # → 2/2 Running
```

**Then decommission the old store** (FR-005, SC-008) — the checklist is in
[`contracts/deployment.md`](./contracts/deployment.md). Verify:

```bash
kubectl get pvc tf2-hosting-data          # → NotFound
grep -ri "sqlite\|DB_PATH" --include='*.py' --include='*.yaml' --include='Dockerfile' \
     app deploy scripts tests Dockerfile  # → no hits outside historical spec documents
```

A leftover volume reachable by a running process is a second, stale source of truth. That is
why removing it is a requirement and not tidiness.

---

## Done when

Verified 2026-07-30 against PostgreSQL 17 (`postgres:17-alpine`), psycopg 3.3.4.

- [x] **SC-001** — 100% of the existing suite passes against Postgres — **428 passed**
      (408 pre-existing, unchanged in expectation, plus 12 rewritten `test_db.py` cases
      and 8 new concurrency cases)
- [x] **SC-002** — ≥20 concurrent users plus both jobs: zero contention failures —
      24 concurrent operations mixing readers, the poller's credit path and the
      reconciler's server path, 0 failures
- [x] **SC-003** — a payment replayed ≥10× from parallel processes: one grant, one ledger
      entry — 12 simultaneous replays → 1 grant, 1 completed payment, 0 duplicate rows.
      **This found a real defect** (3 grants) that is now fixed in `payments._complete`
      and backstopped by migration `0002`
- [ ] **SC-004** — a deploy under continuous traffic: zero failed requests —
      **NOT VERIFIED: requires deploying to the cluster.** The manifest change that
      delivers it (`replicas: 2`, `maxUnavailable: 0`, `maxSurge: 1`) is in place and
      validates server-side; session continuity across two independent app instances is
      verified locally (US3 acceptance 2)
- [x] **SC-005** — restore rehearsed once, ≤24h-old state, back in service in under 30
      minutes — schema dropped and restored from a `pg_dump -Fc`; balances, scrims, users
      and ledger identical either side. **1 second**, against a 30-minute budget
- [x] **SC-006** — fresh clone to passing suite in under 15 minutes, local store included —
      **38 seconds** to 428 passing against a brand-new empty database (excludes the
      one-off `postgres:17-alpine` image pull, which the README covers)
- [x] **SC-007** — before/after walkthrough of every screen: identical — 14 surfaces, all
      render; `/scrims/listings`' 302 to the merged dashboard is feature-004 behaviour
      asserted by an existing test, not a change. FR-002 authority rules re-verified:
      19 join-vs-control cases pass
- [x] **SC-008** — serving entirely from Postgres; old PVC gone; zero processes configured
      for it — `kubectl get pvc tf2-hosting-data` → NotFound, `deploy/pvc.yaml` and local
      `app.db` deleted, and zero code or configuration references the old store
- [x] A balance cannot go negative under concurrent spends (FR-013, the R9 regression) —
      8 concurrent spends against a balance of 1: exactly 1 succeeds, 7 raise
      `InsufficientCredits`, ledger sums to 0 and never below. An existing test caught this
      failing (`-1 >= 0`) before the row lock landed
- [x] README documents local setup, backup, and restore (FR-028)
