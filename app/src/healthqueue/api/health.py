"""Liveness, readiness, and Prometheus metrics endpoints."""

import logging

from fastapi import APIRouter, Request, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

router = APIRouter(tags=["operations"])
log = logging.getLogger(__name__)


@router.get("/healthz")
def liveness() -> dict[str, str]:
    """Process is up. Kubernetes restarts the pod if this fails."""
    return {"status": "ok"}


@router.get("/readyz")
def readiness(request: Request, response: Response) -> dict[str, str]:
    """Dependencies reachable. Kubernetes stops routing traffic if this fails."""
    try:
        request.app.state.store.ping()
    except Exception:
        log.exception("readiness check failed")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "unavailable"}
    return {"status": "ready"}


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
