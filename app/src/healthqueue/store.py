"""SQLite-backed appointment store.

The store is deliberately small and synchronous; its interface (book, get,
find, cancel, booked_between) is what a Postgres implementation would replace.
"""

import sqlite3
import threading
import uuid
from datetime import UTC, datetime

from healthqueue.models import Appointment, AppointmentStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments (
    id          TEXT PRIMARY KEY,
    patient_id  TEXT NOT NULL,
    provider_id TEXT NOT NULL,
    start_utc   TEXT NOT NULL,
    end_utc     TEXT NOT NULL,
    reason      TEXT,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_start ON appointments (provider_id, start_utc);
CREATE INDEX IF NOT EXISTS idx_patient ON appointments (patient_id);
"""


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def _utc(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat()


class AppointmentStore:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def ping(self) -> bool:
        with self._lock:
            return self._conn.execute("SELECT 1").fetchone()[0] == 1

    def book(
        self,
        patient_id: str,
        provider_id: str,
        start: datetime,
        end: datetime,
        reason: str | None,
    ) -> Appointment:
        appt = Appointment(
            id=str(uuid.uuid4()),
            patient_id=patient_id,
            provider_id=provider_id,
            start=start.astimezone(UTC),
            end=end.astimezone(UTC),
            reason=reason,
            status=AppointmentStatus.BOOKED,
            created_at=datetime.now(UTC),
        )
        with self._lock:
            # Check-and-insert under one lock so concurrent requests cannot double-book.
            clash = self._conn.execute(
                "SELECT 1 FROM appointments WHERE status = ? AND "
                "(provider_id = ? OR patient_id = ?) AND start_utc < ? AND end_utc > ?",
                (AppointmentStatus.BOOKED, provider_id, patient_id, _utc(end), _utc(start)),
            ).fetchone()
            if clash:
                raise ConflictError("provider or patient already has an appointment at that time")
            self._conn.execute(
                "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    appt.id,
                    appt.patient_id,
                    appt.provider_id,
                    _utc(appt.start),
                    _utc(appt.end),
                    appt.reason,
                    appt.status,
                    _utc(appt.created_at),
                ),
            )
            self._conn.commit()
        return appt

    def get(self, appointment_id: str) -> Appointment:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM appointments WHERE id = ?", (appointment_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError(appointment_id)
        return self._to_model(row)

    def find(
        self, provider_id: str | None = None, patient_id: str | None = None
    ) -> list[Appointment]:
        query = "SELECT * FROM appointments WHERE 1 = 1"
        params: list[str] = []
        if provider_id:
            query += " AND provider_id = ?"
            params.append(provider_id)
        if patient_id:
            query += " AND patient_id = ?"
            params.append(patient_id)
        query += " ORDER BY start_utc"
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return [self._to_model(r) for r in rows]

    def cancel(self, appointment_id: str) -> Appointment:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE appointments SET status = ? WHERE id = ? AND status = ?",
                (AppointmentStatus.CANCELLED, appointment_id, AppointmentStatus.BOOKED),
            )
            self._conn.commit()
            updated = cur.rowcount
        appt = self.get(appointment_id)  # raises NotFoundError for unknown ids
        if not updated:
            raise ConflictError("appointment is already cancelled")
        return appt

    def booked_between(
        self, provider_id: str, start: datetime, end: datetime
    ) -> list[tuple[datetime, datetime]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT start_utc, end_utc FROM appointments WHERE provider_id = ? "
                "AND status = ? AND start_utc < ? AND end_utc > ?",
                (provider_id, AppointmentStatus.BOOKED, _utc(end), _utc(start)),
            ).fetchall()
        return [(datetime.fromisoformat(s), datetime.fromisoformat(e)) for s, e in rows]

    @staticmethod
    def _to_model(row: sqlite3.Row) -> Appointment:
        return Appointment(
            id=row["id"],
            patient_id=row["patient_id"],
            provider_id=row["provider_id"],
            start=datetime.fromisoformat(row["start_utc"]),
            end=datetime.fromisoformat(row["end_utc"]),
            reason=row["reason"],
            status=AppointmentStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )
