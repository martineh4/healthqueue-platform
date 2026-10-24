import json
import logging

from conftest import booking

from healthqueue.config import Settings
from healthqueue.observability import JsonFormatter


def test_liveness(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readiness(client):
    assert client.get("/readyz").status_code == 200


def test_readiness_fails_when_store_is_down(client, store, monkeypatch):
    def broken():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(store, "ping", broken)
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "unavailable"}


def test_metrics_use_route_templates_not_raw_paths(client):
    appt = client.post("/v1/appointments", json=booking()).json()
    client.get(f"/v1/appointments/{appt['id']}")
    body = client.get("/metrics").text
    assert 'route="/v1/appointments/{appointment_id}"' in body
    assert appt["id"] not in body
    assert "http_request_duration_seconds_bucket" in body
    assert "healthqueue_appointments_booked_total" in body


def test_unmatched_routes_share_one_label(client):
    client.get("/no/such/path")
    assert 'route="unmatched",status="404"' in client.get("/metrics").text


def test_request_id_is_propagated(client):
    resp = client.get("/healthz", headers={"x-request-id": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"
    assert client.get("/healthz").headers["x-request-id"]


def test_access_log_is_json_and_excludes_phi(client, caplog):
    caplog.set_level(logging.INFO, logger="healthqueue.access")
    client.post("/v1/appointments", json=booking(reason="sensitive symptom detail"))
    record = next(r for r in caplog.records if r.name == "healthqueue.access")
    line = json.loads(JsonFormatter().format(record))
    assert line["route"] == "/v1/appointments"
    assert line["status"] == 201
    assert "sensitive" not in json.dumps(line)


def test_settings_from_env(monkeypatch):
    monkeypatch.setenv("HQ_CLINIC_OPEN_HOUR", "8")
    monkeypatch.setenv("HQ_SLOT_MINUTES", "15")
    settings = Settings.from_env()
    assert settings.clinic_open_hour == 8
    assert settings.slot_minutes == 15
    assert settings.db_path == ":memory:"
