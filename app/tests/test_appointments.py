import pytest
from conftest import FUTURE_DAY, booking


def test_book_and_fetch(client):
    created = client.post("/v1/appointments", json=booking())
    assert created.status_code == 201
    appt = created.json()
    assert appt["status"] == "booked"
    assert appt["end"].startswith(f"{FUTURE_DAY}T10:30:00")

    fetched = client.get(f"/v1/appointments/{appt['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == appt


def test_non_utc_start_is_normalised(client):
    resp = client.post("/v1/appointments", json=booking(start=f"{FUTURE_DAY}T05:00:00-05:00"))
    assert resp.status_code == 201
    assert resp.json()["start"].startswith(f"{FUTURE_DAY}T10:00:00")


def test_provider_double_booking_is_rejected(client):
    assert client.post("/v1/appointments", json=booking()).status_code == 201
    clash = client.post(
        "/v1/appointments",
        json=booking(patient_id="pat-2002", start=f"{FUTURE_DAY}T10:15:00Z"),
    )
    assert clash.status_code == 409


def test_patient_double_booking_is_rejected(client):
    assert client.post("/v1/appointments", json=booking()).status_code == 201
    clash = client.post("/v1/appointments", json=booking(provider_id="dr-patel"))
    assert clash.status_code == 409


def test_back_to_back_appointments_are_allowed(client):
    assert client.post("/v1/appointments", json=booking()).status_code == 201
    nxt = client.post(
        "/v1/appointments",
        json=booking(patient_id="pat-2002", start=f"{FUTURE_DAY}T10:30:00Z"),
    )
    assert nxt.status_code == 201


@pytest.mark.parametrize(
    ("overrides", "detail_fragment"),
    [
        ({"start": "2020-01-01T10:00:00Z"}, "future"),
        ({"start": f"{FUTURE_DAY}T10:07:00Z"}, "15-minute"),
        ({"start": f"{FUTURE_DAY}T08:00:00Z"}, "clinic hours"),
        ({"start": f"{FUTURE_DAY}T16:45:00Z", "duration_minutes": 30}, "clinic hours"),
    ],
)
def test_business_rule_validation(client, overrides, detail_fragment):
    resp = client.post("/v1/appointments", json=booking(**overrides))
    assert resp.status_code == 422
    assert detail_fragment in resp.json()["detail"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"start": f"{FUTURE_DAY}T10:00:00"},  # naive datetime
        {"duration_minutes": 20},  # not a multiple of 15
        {"duration_minutes": 180},
        {"patient_id": "bad id with spaces"},
        {"reason": "x" * 501},
    ],
)
def test_schema_validation(client, overrides):
    assert client.post("/v1/appointments", json=booking(**overrides)).status_code == 422


def test_get_unknown_appointment_returns_404(client):
    assert client.get("/v1/appointments/does-not-exist").status_code == 404


def test_list_requires_a_filter(client):
    assert client.get("/v1/appointments").status_code == 422


def test_list_by_provider_and_patient(client):
    client.post("/v1/appointments", json=booking())
    client.post(
        "/v1/appointments",
        json=booking(patient_id="pat-2002", start=f"{FUTURE_DAY}T11:00:00Z"),
    )
    by_provider = client.get("/v1/appointments", params={"provider_id": "dr-chen"}).json()
    assert [a["patient_id"] for a in by_provider] == ["pat-1001", "pat-2002"]
    by_patient = client.get("/v1/appointments", params={"patient_id": "pat-2002"}).json()
    assert len(by_patient) == 1


def test_cancel_frees_the_slot(client):
    appt = client.post("/v1/appointments", json=booking()).json()
    cancelled = client.post(f"/v1/appointments/{appt['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    again = client.post(f"/v1/appointments/{appt['id']}/cancel")
    assert again.status_code == 409

    rebook = client.post("/v1/appointments", json=booking(patient_id="pat-2002"))
    assert rebook.status_code == 201


def test_cancel_unknown_appointment_returns_404(client):
    assert client.post("/v1/appointments/nope/cancel").status_code == 404


def test_availability_excludes_booked_slots(client):
    client.post("/v1/appointments", json=booking(duration_minutes=60))
    resp = client.get("/v1/providers/dr-chen/availability", params={"date": FUTURE_DAY})
    assert resp.status_code == 200
    starts = [s["start"][11:16] for s in resp.json()["slots"]]
    assert len(starts) == 14  # 16 half-hour slots between 09:00 and 17:00, minus 2 booked
    assert "10:00" not in starts and "10:30" not in starts
    assert starts[0] == "09:00" and starts[-1] == "16:30"


def test_availability_ignores_cancelled_appointments(client):
    appt = client.post("/v1/appointments", json=booking()).json()
    client.post(f"/v1/appointments/{appt['id']}/cancel")
    slots = client.get("/v1/providers/dr-chen/availability", params={"date": FUTURE_DAY}).json()[
        "slots"
    ]
    assert len(slots) == 16
