"""Application factory and ASGI entrypoint (`uvicorn healthqueue.main:app`)."""

from fastapi import FastAPI

from healthqueue import __version__
from healthqueue.api import appointments, health
from healthqueue.config import Settings
from healthqueue.observability import configure_logging, observe_request
from healthqueue.store import AppointmentStore


def create_app(settings: Settings | None = None, store: AppointmentStore | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)

    app = FastAPI(
        title="HealthQueue Appointment API",
        version=__version__,
        description="Patient-facing appointment scheduling for HealthQueue clinics.",
    )
    app.state.settings = settings
    app.state.store = store or AppointmentStore(settings.db_path)
    app.middleware("http")(observe_request)
    app.include_router(health.router)
    app.include_router(appointments.router)
    return app


app = create_app()
