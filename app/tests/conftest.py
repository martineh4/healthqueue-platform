from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from healthqueue.config import Settings
from healthqueue.main import create_app
from healthqueue.store import AppointmentStore

FUTURE_DAY = "2030-03-04"


@pytest.fixture
def store() -> Iterator[AppointmentStore]:
    s = AppointmentStore(":memory:")
    yield s
    s.close()


@pytest.fixture
def client(store: AppointmentStore) -> TestClient:
    return TestClient(create_app(Settings(), store))


def booking(**overrides):
    body = {
        "patient_id": "pat-1001",
        "provider_id": "dr-chen",
        "start": f"{FUTURE_DAY}T10:00:00Z",
        "duration_minutes": 30,
        "reason": "Annual check-up",
    }
    body.update(overrides)
    return body
