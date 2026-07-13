"""Readiness endpoint (FR-008). Used as the k8s readiness probe so traffic is not
routed to a pod that is still starting."""
from flask import Blueprint, current_app

bp = Blueprint("health", __name__)


@bp.get("/healthz")
def healthz():
    if not current_app.config.get("READY", True):
        return "not ready", 503
    return "ok", 200
