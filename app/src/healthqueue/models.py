"""Request/response schemas."""

from datetime import date, datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class AppointmentStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


class AppointmentCreate(BaseModel):
    patient_id: str = Field(pattern=ID_PATTERN, examples=["pat-1001"])
    provider_id: str = Field(pattern=ID_PATTERN, examples=["dr-chen"])
    start: AwareDatetime = Field(examples=["2030-03-04T10:00:00Z"])
    duration_minutes: int = Field(default=30, ge=15, le=120, multiple_of=15)
    # Free text may contain PHI: it is stored but never logged.
    reason: str | None = Field(default=None, max_length=500)


class Appointment(BaseModel):
    id: str
    patient_id: str
    provider_id: str
    start: datetime
    end: datetime
    reason: str | None
    status: AppointmentStatus
    created_at: datetime


class Slot(BaseModel):
    start: datetime
    end: datetime


class Availability(BaseModel):
    provider_id: str
    date: date
    slots: list[Slot]
