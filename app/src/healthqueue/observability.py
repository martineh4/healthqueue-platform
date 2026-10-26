"""Metrics and structured logging.

SLI design notes (see docs/observability.md):
- Requests are labelled by *route template* (e.g. /v1/appointments/{appointment_id}),
  never the raw path, to keep label cardinality bounded and avoid leaking IDs.
- Latency buckets bracket the 300 ms latency SLO threshold so the SLI can be
  computed exactly from bucket counts.
- Logs are JSON, carry a request ID, and never include bodies or query strings,
  which may contain PHI.
"""

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "http_requests_total",
    "HTTP requests by route template and status code.",
    ["method", "route", "status"],
)
LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency by route template.",
    ["method", "route"],
    buckets=(0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0),
)
BOOKINGS = Counter("healthqueue_appointments_booked_total", "Appointments successfully booked.")
BOOKING_CONFLICTS = Counter(
    "healthqueue_booking_conflicts_total", "Booking attempts rejected due to a time clash."
)
CANCELLATIONS = Counter("healthqueue_appointments_cancelled_total", "Appointments cancelled.")

access_log = logging.getLogger("healthqueue.access")


class JsonFormatter(logging.Formatter):
    _EXTRA_FIELDS = ("request_id", "method", "route", "status", "duration_ms")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for field in self._EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


async def observe_request(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    start = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
    finally:
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        REQUESTS.labels(request.method, template, str(status)).inc()
        LATENCY.labels(request.method, template).observe(elapsed)
        access_log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "route": template,
                "status": status,
                "duration_ms": round(elapsed * 1000, 2),
            },
        )
    response.headers["x-request-id"] = request_id
    return response
