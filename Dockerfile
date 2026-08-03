# Multi-stage build, "the iriga way": cook the (slow) dependency layer ONCE in a
# shared stage, separately from fast-changing app code, then a slim non-root final
# image. In Rust that layer is `cargo chef cook`; the Python equivalent is a
# `pip install -r requirements.txt` that only re-runs when requirements.txt changes.
# Build in a single buildkit session and push to harbor.irulast.com.

# The base is Alpine, and pinned by digest. Both of those are load-bearing:
#
#   Alpine, because Harbor's project policy ("prevent images with severity Critical or
#   higher from running") refuses the *pull* with 412 PROJECTPOLICYVIOLATION. On
#   python:3.12-slim — which now resolves to Debian 13 — the image carries 4 criticals,
#   all in `perl-base`, all unfixable (won't-fix / fix_deferred). Nothing here uses perl;
#   it just comes with the base. python:3.12-alpine scores 0 criticals / 9 total.
#   Do NOT "fix" this by moving to -slim-bookworm: that is worse (6 criticals, adding
#   zlib1g CVE-2023-45853 and libsqlite3-0 CVE-2025-7458).
#
#   By digest, because this broke with no commit to this repo — the floating tag drifted
#   onto Debian 13 and newly published CVEs, and the first sign was a production
#   ImagePullBackOff. Bumping the base is now a deliberate commit that CI scans.
#   To bump: `docker buildx imagetools inspect python:3.12-alpine` and take the top-level
#   (index) digest, not a per-platform one, or non-amd64 builds break.
#
# --- deps stage: install pinned deps into an isolated prefix (cached layer) ------
FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS deps
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# Only requirements.txt is copied here, so this layer is reused on code-only changes.
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# --- final stage: slim, non-root runtime -----------------------------------------
FROM python:3.12-alpine@sha256:6d43704baacd1bfbe7c295d7f13079d5d8104ed33568873133f8fc69980419df AS app
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_PORT=8000

# Copy the installed dependencies from the deps stage.
COPY --from=deps /install /usr/local

# Copy only application code (kept separate from the deps layer above).
COPY app/ ./app/
COPY wsgi.py ./
# Schema migrations are read at startup by `migrate()`, so they ship in the image. They
# are declarative state that reaches an environment through the repo, the same as the
# manifests in guilding-for-the-folks/managed-services (Principle VI).
COPY migrations/ ./migrations/

# Run as a non-root user (Principle IV / VII). `adduser -S -H`, not `useradd`: busybox
# has no useradd. `-S` is a system account, `-H` skips the home directory. The resulting
# account is uid 10001 but gid 65533 (nogroup) — Alpine's -S does not mint a matching
# group — so pin runAsGroup in the Deployment if anything ever depends on gid 10001.
#
# No data directory and no VOLUME: as of feature 006 the store is PostgreSQL, reached over
# the network via DATABASE_URL. With nothing local to write, `readOnlyRootFilesystem: true`
# needs no writable path carved out for it at all — a strictly smaller surface than the
# PVC this replaced, and one fewer place for a second, stale copy of the data to live.
RUN adduser -S -H -u 10001 appuser
USER appuser

EXPOSE 8000
# Gunicorn serves the WSGI app; the Flask dev server is never used in the container.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "wsgi:app"]
