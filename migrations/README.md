# Migrations

Ordered SQL migrations for the metadata store (feature 006, FR-019). Applied by
`migrate()` in [`app/db.py`](../app/db.py) at startup, under a Postgres advisory lock so
several app copies starting at once initialise exactly once (FR-015).

## The rules

1. **Applied in filename order.** `0001_`, `0002_`, … — zero-padded, so lexicographic
   order is the order they run in. The filename stem is the version recorded in
   `schema_migrations`.
2. **One file per change.** A migration is a single, reviewable unit. Do not bundle
   unrelated schema changes into one file because they happened the same week.
3. **Never edit a file that has been applied anywhere.** Not in production, not on a
   teammate's machine. An applied version is already recorded in `schema_migrations` and
   will never run again, so an edit silently produces two different schemas that both
   claim to be at the same version. Fix a mistake with a *new* migration.
4. **Plain SQL, no templating.** These files are handed to Postgres as-is. Anything that
   needs application logic is not a migration.

## Why this and not a framework

FR-019 asks for "a repeatable, ordered mechanism recorded in the repository". That is a
page of code (see `migrate()`), not a dependency. Alembic would drag in SQLAlchemy — a
large library whose ORM this app does not use and will not use (research R1). Recorded in
[research.md R13](../specs/006-postgres-datastore/research.md).

## Notes

- **DDL in Postgres is transactional.** Each migration runs inside its own transaction, so
  one that fails halfway leaves nothing half-created and its version is not recorded.
- `0001_initial.sql` is the whole schema in one file, because the store starts empty
  (FR-004) — there is no data to carry across and therefore nothing to migrate *from*.
