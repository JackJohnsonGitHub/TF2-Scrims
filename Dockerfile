# Multi-stage build, "the iriga way": cook the (slow) dependency layer ONCE in a
# shared stage, separately from fast-changing app code, then a slim non-root final
# image. In Rust that layer is `cargo chef cook`; the Python equivalent is a
# `pip install -r requirements.txt` that only re-runs when requirements.txt changes.
# Build in a single buildkit session and push to harbor.irulast.com.

# --- deps stage: install pinned deps into an isolated prefix (cached layer) ------
FROM python:3.12-slim AS deps
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
# Only requirements.txt is copied here, so this layer is reused on code-only changes.
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt

# --- final stage: slim, non-root runtime -----------------------------------------
FROM python:3.12-slim AS app
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

# Run as a non-root user (Principle IV / VII).
#
# No data directory and no VOLUME: as of feature 006 the store is PostgreSQL, reached over
# the network via DATABASE_URL. With nothing local to write, `readOnlyRootFilesystem: true`
# needs no writable path carved out for it at all — a strictly smaller surface than the
# PVC this replaced, and one fewer place for a second, stale copy of the data to live.
RUN useradd --system --uid 10001 --no-create-home appuser
USER appuser

EXPOSE 8000
# Gunicorn serves the WSGI app; the Flask dev server is never used in the container.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "wsgi:app"]
