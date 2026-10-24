"""Runtime configuration, read from environment variables (12-factor)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str = ":memory:"
    clinic_open_hour: int = 9  # UTC
    clinic_close_hour: int = 17  # UTC
    slot_minutes: int = 30
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            db_path=os.getenv("HQ_DB_PATH", cls.db_path),
            clinic_open_hour=int(os.getenv("HQ_CLINIC_OPEN_HOUR", cls.clinic_open_hour)),
            clinic_close_hour=int(os.getenv("HQ_CLINIC_CLOSE_HOUR", cls.clinic_close_hour)),
            slot_minutes=int(os.getenv("HQ_SLOT_MINUTES", cls.slot_minutes)),
            log_level=os.getenv("HQ_LOG_LEVEL", cls.log_level),
        )
