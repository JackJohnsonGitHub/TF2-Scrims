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

    # SQLite database path (user accounts). Local file in dev; a PVC-backed path in
    # the container.
    DB_PATH = os.environ.get("DB_PATH", "app.db")

    # RGL public API (profile + current teams, keyed by SteamID64). Public and
    # keyless; called only on link/refresh, never per page load. The short timeout
    # keeps an RGL outage from taking the page down (Principle VII).
    RGL_API_BASE = os.environ.get("RGL_API_BASE", "https://api.rgl.gg/v0").rstrip("/")
    RGL_TIMEOUT_SECONDS = float(os.environ.get("RGL_TIMEOUT_SECONDS", "5"))

    # Team rosters are cached in SQLite and refetched from RGL at most this often
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

    # Deployment environment marker; "production" forbids the insecure SECRET_KEY.
    ENV = os.environ.get("APP_ENV", "development")

    @staticmethod
    def validate() -> None:
        """Fail fast if a real secret is missing in production (Principle IV)."""
        if Config.ENV == "production" and (not os.environ.get("APP_SECRET_KEY")):
            raise RuntimeError(
                "APP_SECRET_KEY is required in production (source it from OpenBao)."
            )
