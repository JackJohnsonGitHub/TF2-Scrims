"""Environment-driven configuration for the TF2 hosting control-plane app.

No secrets live here — per the project constitution, secrets come from OpenBao and
are never hardcoded. This module only reads them from the environment.
"""
import os
from datetime import timedelta


class Config:
    # Bind address for the WSGI server (Gunicorn reads these via wsgi.py / env).
    HOST = os.environ.get("APP_HOST", "0.0.0.0")
    PORT = int(os.environ.get("APP_PORT", "8000"))

    # Readiness flag. The app is considered ready once the factory has built it;
    # this env override exists so a deployment can force not-ready during drains.
    READY = os.environ.get("APP_READY", "1") == "1"

    # Session-signing key. Now security-relevant (signs the sign-in cookie), so it
    # MUST be provided from OpenBao in real deploys. The dev fallback only applies
    # when APP_ENV != "production"; production without a key fails fast (see below).
    SECRET_KEY = os.environ.get("APP_SECRET_KEY") or "dev-not-a-secret"

    # Steam Web API key (persona name + avatar lookup). From OpenBao; optional in
    # dev (persona/avatar just fall back when absent).
    STEAM_API_KEY = os.environ.get("STEAM_API_KEY", "")

    # Public base URL = the OpenID realm / return_to target. Steam redirects the
    # browser back here, so it must match the deployed origin.
    BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")

    # The metadata store (feature 006). A libpq connection string, which contains a
    # password and is therefore a secret by constitution IV: from OpenBao in real deploys,
    # never committed, never logged, never rendered into a page. `app/db.py` redacts it to
    # host:port/dbname anywhere it has to be reported.
    #
    # One engine everywhere — development, tests, and deployment (FR-025) — so the local
    # default points at the container the README tells you to start, rather than at
    # anything that would let the suite quietly run against a different engine.
    DATABASE_URL = os.environ.get(
        "DATABASE_URL", "postgresql://tf2app:dev@localhost:5432/tf2hosting"
    )

    # Connection pool, per process. Gunicorn runs 2 sync workers and a sync worker handles
    # one request at a time, so 4 is headroom rather than tuning. Budget: 2 pods × 2
    # workers × 4, plus CronJob peaks ≈ 20 against Postgres's default max_connections=100.
    DB_POOL_MIN = int(os.environ.get("DB_POOL_MIN", "1"))
    DB_POOL_MAX = int(os.environ.get("DB_POOL_MAX", "4"))

    # How long to wait for a connection before failing. Bounded deliberately: an
    # unreachable store must surface as a failed readiness check (FR-016), not a hang.
    DB_CONNECT_TIMEOUT = float(os.environ.get("DB_CONNECT_TIMEOUT", "5"))

    # RGL public API (profile + current teams, keyed by SteamID64). Public and
    # keyless; called only on link/refresh, never per page load. The short timeout
    # keeps an RGL outage from taking the page down (Principle VII).
    RGL_API_BASE = os.environ.get("RGL_API_BASE", "https://api.rgl.gg/v0").rstrip("/")
    RGL_TIMEOUT_SECONDS = float(os.environ.get("RGL_TIMEOUT_SECONDS", "5"))

    # Team rosters are cached in the store and refetched from RGL at most this often
    # (on listing-detail views only — never on the dashboard path).
    RGL_ROSTER_TTL_SECONDS = float(os.environ.get("RGL_ROSTER_TTL_SECONDS", "3600"))

    # Season directory for the propose flow's division browser (research §8):
    # season registrations refresh at most daily, and each browse request hydrates
    # at most this many not-yet-known teams — bounded, no background jobs.
    RGL_DIRECTORY_TTL_SECONDS = float(os.environ.get("RGL_DIRECTORY_TTL_SECONDS", "86400"))
    RGL_HYDRATE_BATCH = int(os.environ.get("RGL_HYDRATE_BATCH", "20"))

    # Signed-in sessions are persistent; requests past this age are treated as
    # signed out. Default ~30 days; tunable via APP_SESSION_DAYS.
    PERMANENT_SESSION_LIFETIME = timedelta(days=int(os.environ.get("APP_SESSION_DAYS", "30")))

    # --- Payment & credits (feature 005) ----------------------------------------
    # Where a paying user is sent to open a trade offer. Contains a token, so it is
    # a secret by constitution IV: from OpenBao, never committed, never rendered
    # into a page as text — only used as a redirect destination.
    OPERATOR_TRADE_URL = os.environ.get("OPERATOR_TRADE_URL", "")

    # What counts as payment. Scoped by appid because other games ship items with
    # confusingly similar names and those must not count (FR-049).
    PAYMENT_ITEM_NAME = os.environ.get("PAYMENT_ITEM_NAME", "Mann Co. Supply Crate Key")
    PAYMENT_ITEM_APPID = int(os.environ.get("PAYMENT_ITEM_APPID", "440"))
    PAYMENT_MIN_KEYS = int(os.environ.get("PAYMENT_MIN_KEYS", "2"))

    # The price, kept configurable so it can move with the market without a code
    # change (FR-051). 2 keys → 5 credits, i.e. 2.5 credits per key; credits are
    # granted as floor(keys × rate) so no fractional remainder has to be tracked.
    CREDITS_PER_KEY = float(os.environ.get("CREDITS_PER_KEY", "2.5"))

    # What a credit buys. One credit runs a server for CREDIT_MINUTES; extending
    # costs one credit for EXTENSION_MINUTES (deliberately half the rate).
    CREDIT_MINUTES = int(os.environ.get("CREDIT_MINUTES", "60"))
    EXTENSION_MINUTES = int(os.environ.get("EXTENSION_MINUTES", "30"))

    # Unpaid overrun buffer past a runtime window. Matches commonly run slightly
    # long; granted once per server, never once per extension (FR-074).
    GRACE_MINUTES = int(os.environ.get("GRACE_MINUTES", "15"))

    # How often the payment poller runs. 60s is ~1,440 calls/day against Steam's
    # 100,000/day budget — about 1.4%.
    PAYMENT_POLL_SECONDS = int(os.environ.get("PAYMENT_POLL_SECONDS", "60"))

    # Deployment environment marker; "production" forbids the insecure SECRET_KEY.
    ENV = os.environ.get("APP_ENV", "development")

    @staticmethod
    def validate() -> None:
        """Fail fast if a real secret is missing in production (Principle IV)."""
        if Config.ENV == "production" and (not os.environ.get("APP_SECRET_KEY")):
            raise RuntimeError(
                "APP_SECRET_KEY is required in production (source it from OpenBao)."
            )
        # STEAM_API_KEY used to be optional — persona and avatar simply degraded
        # without it. Payment changes that: without a key the poller cannot see a
        # single trade, so every payment would sit unpaid forever with nothing in
        # the app looking wrong. That must be a startup failure, not a silence.
        if Config.ENV == "production":
            missing = [name for name in ("STEAM_API_KEY", "OPERATOR_TRADE_URL")
                       if not os.environ.get(name)]
            if missing:
                raise RuntimeError(
                    f"{', '.join(missing)} required in production: payment cannot "
                    "complete without them, and the failure would be silent. "
                    "Source them from OpenBao."
                )
        # DATABASE_URL has a local-dev default so a developer can start without ceremony.
        # In production that default would point at nothing, and the app would come up and
        # fail every request instead of failing to come up — so require it explicitly
        # (FR-020, and the same fail-fast treatment as every other secret above).
        if Config.ENV == "production" and not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL is required in production (source it from OpenBao). "
                "Without it the app would start against a store that does not exist."
            )
