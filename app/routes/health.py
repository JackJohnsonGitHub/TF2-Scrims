"""Readiness endpoint. Used as the k8s readiness probe so traffic is not routed to a pod
that is still starting — or to one that cannot reach the metadata store.

**The store round trip is the point, not a side effect** (006/FR-016). Returning `ok` as
long as the process is up would let Kubernetes send traffic to a pod whose store is
unreachable, and every page would render normally and show nothing. That silent mode is
the specific failure this endpoint exists to prevent, and it gets worse with more than one
replica: one broken pod would quietly serve empty dashboards alongside healthy ones.

There is deliberately no liveness probe on this path. Readiness failing takes a pod out of
the Service until the store returns; liveness failing would restart it, which fixes nothing
during a store outage and would turn a brief interruption into a crash loop.
"""
import logging

from flask import Blueprint, current_app

from ..db import check, redact_dsn

bp = Blueprint("health", __name__)

log = logging.getLogger(__name__)


@bp.get("/healthz")
def healthz():
    if not current_app.config.get("READY", True):
        return "not ready", 503

    try:
        check()
    except Exception as exc:  # noqa: BLE001 — any failure to reach the store is not-ready
        # Logged with the DSN redacted to host:port/dbname. An operator needs to know
        # *which* store was unreachable; the credentials are never part of that
        # (constitution IV).
        log.error("readiness failed: store %s unreachable: %s: %s",
                  redact_dsn(), type(exc).__name__, exc)
        # No database error text in the response body: Postgres messages name tables,
        # columns and constraints, which is operator information, not user information.
        return "not ready", 503

    return "ok", 200
