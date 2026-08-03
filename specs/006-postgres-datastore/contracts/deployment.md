# Contract: Running the store on `mke`

**Feature**: `006-postgres-datastore` · Companion to
[`store-access.md`](./store-access.md).

Everything needed to run and reach the store lives in this repository under version control
(FR-021, constitution VI). Nothing here is applied by hand on the cluster.

---

## Manifests

| File | Kind | Status |
|---|---|---|
| `deploy/postgres-statefulset.yaml` | StatefulSet | **NEW** — single instance, `postgres:17-alpine` |
| `deploy/postgres-service.yaml` | Service (ClusterIP) | **NEW** — stable name the app connects to |
| `deploy/postgres-pvc.yaml` | PVC (via `volumeClaimTemplates`) | **NEW** — the store's data volume |
| `deploy/cronjob-backup-postgres.yaml` | CronJob | **NEW** — scheduled `pg_dump` |
| `deploy/backup-pvc.yaml` | PVC | **NEW** — where dumps land, separate from the store's own volume |
| `deploy/deployment.yaml` | Deployment | **CHANGED** — `replicas: 2`, `RollingUpdate`, `DATABASE_URL`, no `data` volume |
| `deploy/cronjob-poll-payments.yaml` | CronJob | **CHANGED** — `DATABASE_URL`, no `data` volume |
| `deploy/cronjob-reconcile-servers.yaml` | CronJob | **CHANGED** — `DATABASE_URL`, no `data` volume |
| `deploy/secret.example.yaml` | Secret (template) | **CHANGED** — adds `database-url` |
| `deploy/pvc.yaml` | PVC | **DELETED** — the SQLite volume (FR-005, SC-008) |

**The backup PVC is separate from the store's PVC on purpose.** A dump that lives on the
volume it is a backup of is not a backup.

---

## Secrets (FR-020, constitution IV)

`DATABASE_URL` is added to the existing `tf2-hosting-secrets` Secret, sourced from OpenBao at
`secrets.irulast.com` by the operator, exactly as `app-secret-key`, `steam-api-key`, and
`operator-trade-url` are today.

```yaml
# deploy/secret.example.yaml (committed template — never real values)
stringData:
  database-url: "postgresql://tf2app:REPLACE-ME@tf2-hosting-postgres:5432/tf2hosting"
```

The Postgres StatefulSet reads the **same** credential material for `POSTGRES_PASSWORD`, so
there is one password in one place. It MUST NOT be committed, logged, or sent to any client.

---

## StatefulSet shape

| Setting | Value | Why |
|---|---|---|
| `replicas` | `1` | Replication and failover are out of scope (spec, Out of Scope) |
| `updateStrategy` | `RollingUpdate` | One instance, so this is an ordered restart |
| `securityContext` | `runAsNonRoot`, uid `70` (alpine postgres) | Constitution IV |
| `resources.limits` | `cpu: 1`, `memory: 1Gi` | **FR-022** — cannot starve the node or other tenants (Principle VII) |
| `resources.requests` | `cpu: 100m`, `memory: 256Mi` | Modest scale: low hundreds of teams |
| `livenessProbe` | `pg_isready` | |
| `readinessProbe` | `pg_isready` | The app's own readiness depends on reaching this |
| `volumeClaimTemplates` | 10Gi | Metadata only — no game-server data ever lands here |

`shared_buffers` and friends stay at defaults. Spec Assumptions: "this feature is about
correctness and availability under concurrency, not throughput."

**Deferred operational check** (research R15): the cluster was unreachable while planning
(VPN down), so the default StorageClass name and its access modes must be confirmed before
these manifests are applied.

---

## App Deployment changes

```yaml
replicas: 2                      # was 1 — User Story 3, impossible with a RWO PVC attached
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 0            # SC-004: zero failed requests during a deploy
    maxSurge: 1
```

- `DB_PATH` env removed; `DATABASE_URL` added from the Secret.
- The `data` volume and its `volumeMount` removed. `readOnlyRootFilesystem: true` stays — with
  no PVC the app needs no writable path at all.
- The readiness probe is unchanged in shape but now means something stronger: `/healthz`
  performs a store round trip (FR-016), so a pod that cannot reach Postgres is pulled from the
  Service rather than serving empty pages.

`maxUnavailable: 0` is what makes User Story 3 true rather than aspirational: a new pod must
pass its store-backed readiness check before an old one is taken down.

**Session continuity across copies** (US3 acceptance 2) needs no work: sessions are signed
cookies keyed by `APP_SECRET_KEY`, which both pods read from the same Secret. There is no
server-side session state to share.

---

## CronJob changes

Both existing CronJobs lose their PVC mount and gain `DATABASE_URL`.

The comment in `cronjob-poll-payments.yaml` — *"Shares the app's PVC, so it must not run
while the Deployment is mid-migration"* — **is deleted along with the constraint it
describes**. That sentence was a symptom of the single-volume topology; a CronJob that can
now write concurrently with two app pods is the whole point of the feature.

`concurrencyPolicy: Forbid` stays. It is cheap defence in depth, and the exactly-once
guarantee remains the database constraint (FR-009), not the scheduler.

---

## Backup (FR-017)

`deploy/cronjob-backup-postgres.yaml` — daily, outside scrim hours.

```
pg_dump --format=custom --dbname="$DATABASE_URL" --file=/backups/tf2hosting-<UTC timestamp>.dump
```

| Aspect | Contract |
|---|---|
| Format | `-Fc` custom — compressed, restorable selectively with `pg_restore` |
| Destination | The dedicated backup PVC, mounted at `/backups` |
| Naming | `tf2hosting-YYYYMMDDTHHMMSSZ.dump` — sorts chronologically |
| Retention | Keep the most recent N daily dumps; prune older in the same job |
| Schedule | Daily. SC-005 asks for recovery to a state **no more than 24 hours old** |
| `concurrencyPolicy` | `Forbid` |
| `failedJobsHistoryLimit` | `5` — a failing backup's logs are the ones worth keeping |

**Visibility** — FR-017's second half requires the operator to see whether the most recent
backup succeeded and when. Two ways, because a silently-stopped backup is the failure mode
worth engineering against:

1. Job history: `kubectl get jobs -l component=backup --sort-by=.status.startTime`
2. Each successful run writes `/backups/latest.json`:
   ```json
   {"completed_at": "2026-07-31T03:00:12Z", "file": "tf2hosting-20260731T030004Z.dump", "bytes": 184320}
   ```
   Readable without parsing logs, and a stale `completed_at` is itself the alarm.

---

## Restore (FR-018)

An operator action, not automatic — spec, Out of Scope: "Automatic failover of the store;
recovery is an operator action."

```bash
# 1. Stop writers so nothing races the restore.
kubectl scale deployment/tf2-hosting-app --replicas=0
kubectl patch cronjob/tf2-hosting-poll-payments -p '{"spec":{"suspend":true}}'
kubectl patch cronjob/tf2-hosting-reconcile-servers -p '{"spec":{"suspend":true}}'

# 2. Restore into a fresh database.
kubectl exec -it tf2-hosting-postgres-0 -- \
  psql -U postgres -c 'DROP DATABASE IF EXISTS tf2hosting; CREATE DATABASE tf2hosting OWNER tf2app;'
kubectl exec -i tf2-hosting-postgres-0 -- \
  pg_restore --dbname="$DATABASE_URL" --no-owner < tf2hosting-<timestamp>.dump

# 3. Bring writers back.
kubectl scale deployment/tf2-hosting-app --replicas=2
kubectl patch cronjob/tf2-hosting-poll-payments -p '{"spec":{"suspend":false}}'
kubectl patch cronjob/tf2-hosting-reconcile-servers -p '{"spec":{"suspend":false}}'
```

**SC-005 requires this be rehearsed at least once, and completed within 30 minutes.** The
runnable version with verification steps is in [`quickstart.md`](../quickstart.md) — an
incident is the wrong time to find out whether the dumps restore.

**US2 acceptance 2** is the check that matters after any restore: every user's balance equals
the sum of their restored ledger entries. It holds by construction — there is no stored total
that could survive a restore disagreeing with the rows (FR-013) — but it is verified anyway,
because "by construction" is a claim until something checks it.

---

## Decommissioning the old store (FR-005, SC-008)

Not optional, and not "leave it, it's harmless": a leftover database file reachable by any
running process is a second, stale source of truth the platform could silently read from.

- [ ] `deploy/pvc.yaml` deleted from the repository
- [ ] `data` volume and `volumeMount` removed from `deployment.yaml` and **both** CronJobs
- [ ] `kubectl delete pvc tf2-hosting-data` on the cluster
- [ ] `DB_PATH` gone from `config.py`, `Dockerfile` (env, `/data` mkdir, chown, `VOLUME`),
      README, and every manifest
- [ ] Local `app.db` deleted; `.gitignore`'s "SQLite user DB lives on a PVC" comment corrected
- [ ] `grep -ri sqlite` over the repository returns only historical spec documents

**SC-008 is verified by that last line**: after cutover, zero processes are configured to
reach the old store.

---

## Cutover

The platform has never served real users (spec, Clarifications), so this takes a brief planned
interruption — **for this cutover only**, not as ongoing practice.

1. Apply the Postgres StatefulSet, Service, and Secret; wait for `pg_isready`.
2. Apply the updated app Deployment (`replicas: 2`) and CronJobs. First pod in runs
   `migrate()` under the advisory lock; the second finds the schema present (FR-015).
3. Verify `/healthz` on both pods, then walk the screens (SC-007).
4. Seed demo data if this is a development or demo environment (FR-006).
5. Delete the old PVC and confirm the decommission checklist above.

**A server mid-window at cutover** (spec Edge Cases) needs no special handling: the store
starts empty, so no server, window, or credit survives the cutover to be restarted or
re-charged. This is a consequence of starting empty, and it is only acceptable *because*
there are no real users — worth stating so nobody assumes a migration path exists.
