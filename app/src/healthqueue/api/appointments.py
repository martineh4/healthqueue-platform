"""Appointment booking, lookup, cancellation, and provider availability."""

from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status

from healthqueue.config import Settings
from healthqueue.models import ID_PATTERN, Appointment, AppointmentCreate, Availability, Slot
from healthqueue.observability import BOOKING_CONFLICTS, BOOKINGS, CANCELLATIONS
from healthqueue.store import AppointmentStore, ConflictError, NotFoundError

router = APIRouter(prefix="/v1", tags=["appointments"])

ProviderId = Annotated[str, Path(pattern=ID_PATTERN)]


def get_store(request: Request) -> AppointmentStore:
    return request.app.state.store


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


StoreDep = Annotated[AppointmentStore, Depends(get_store)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def _within_clinic_hours(start: datetime, end: datetime, settings: Settings) -> bool:
    day = start.date()
    open_at = datetime.combine(day, time(settings.clinic_open_hour), UTC)
    close_at = datetime.combine(day, time(settings.clinic_close_hour), UTC)
    return open_at <= start and end <= close_at


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
def book_appointment(
    body: AppointmentCreate, store: StoreDep, settings: SettingsDep
) -> Appointment:
    start = body.start.astimezone(UTC)
    end = start + timedelta(minutes=body.duration_minutes)
    if start <= datetime.now(UTC):
        raise HTTPException(422, "start must be in the future")
    if start.minute % 15 or start.second or start.microsecond:
        raise HTTPException(422, "start must align to a 15-minute boundary")
    if not _within_clinic_hours(start, end, settings):
        raise HTTPException(
            422,
            f"appointment must fall within clinic hours "
            f"{settings.clinic_open_hour:02d}:00-{settings.clinic_close_hour:02d}:00 UTC",
        )
    try:
        appt = store.book(body.patient_id, body.provider_id, start, end, body.reason)
    except ConflictError as exc:
        BOOKING_CONFLICTS.inc()
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    BOOKINGS.inc()
    return appt


@router.get("/appointments")
def list_appointments(
    store: StoreDep,
    provider_id: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
    patient_id: Annotated[str | None, Query(pattern=ID_PATTERN)] = None,
) -> list[Appointment]:
    if not provider_id and not patient_id:
        raise HTTPException(422, "filter by provider_id or patient_id")
    return store.list(provider_id=provider_id, patient_id=patient_id)


@router.get("/appointments/{appointment_id}")
def get_appointment(appointment_id: str, store: StoreDep) -> Appointment:
    try:
        return store.get(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appointment not found") from exc


@router.post("/appointments/{appointment_id}/cancel")
def cancel_appointment(appointment_id: str, store: StoreDep) -> Appointment:
    try:
        appt = store.cancel(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "appointment not found") from exc
    except ConflictError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    CANCELLATIONS.inc()
    return appt


@router.get("/providers/{provider_id}/availability")
def provider_availability(
    provider_id: ProviderId,
    day: Annotated[date, Query(alias="date")],
    store: StoreDep,
    settings: SettingsDep,
) -> Availability:
    open_at = datetime.combine(day, time(settings.clinic_open_hour), UTC)
    close_at = datetime.combine(day, time(settings.clinic_close_hour), UTC)
    booked = store.booked_between(provider_id, open_at, close_at)
    step = timedelta(minutes=settings.slot_minutes)
    slots: list[Slot] = []
    cursor = open_at
    while cursor + step <= close_at:
        slot_end = cursor + step
        if not any(b_start < slot_end and b_end > cursor for b_start, b_end in booked):
            slots.append(Slot(start=cursor, end=slot_end))
        cursor = slot_end
    return Availability(provider_id=provider_id, date=day, slots=slots)
