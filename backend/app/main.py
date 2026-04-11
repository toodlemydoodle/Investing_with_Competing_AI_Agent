from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.db.migrations import migrate_legacy_schema
from app.db.session import Base
from app.db.session import SessionLocal
from app.db.session import engine
from app.models.entities import Alert
from app.services.dashboard_stream import mark_dashboard_state_updated
from app.services.trading import bootstrap_database
from app.services.trading import close_broker_adapters
from app.services.trading import set_setting_value
from app.strategy.engine import get_autopilot_enabled
from app.strategy.engine import run_agent_autopilot_cycle
from app.strategy.engine import set_autopilot_enabled

AUTH_FAILURE_FRAGMENTS = (
    'login devices has exceeded the limit',
    'currently logged out',
    'logged out',
    'unlock_trade failed',
    'OpenD connection failed',
)


def _is_broker_auth_failure(message: str) -> bool:
    lowered = message.lower()
    return any(fragment.lower() in lowered for fragment in AUTH_FAILURE_FRAGMENTS)


def _pause_autopilot_for_broker_failure(error_message: str) -> None:
    summary = 'Autopilot paused because moomoo/OpenD logged out or hit the device limit. Log into OpenD again, then re-enable autopilot.'
    with SessionLocal() as db:
        set_autopilot_enabled(db, False)
        set_setting_value(db, 'agent_autopilot_last_cycle_at', datetime.utcnow().isoformat())
        set_setting_value(db, 'agent_autopilot_last_summary', summary)
        existing = db.query(Alert).filter(Alert.title == 'Autopilot paused').one_or_none()
        if existing is None:
            db.add(
                Alert(
                    severity='warning',
                    title='Autopilot paused',
                    message=f'{summary} Broker detail: {error_message}',
                    is_active=True,
                )
            )
        else:
            existing.severity = 'warning'
            existing.message = f'{summary} Broker detail: {error_message}'
            existing.is_active = True
            existing.updated_at = datetime.utcnow()
        db.commit()
    mark_dashboard_state_updated('autopilot-paused')


def _run_autopilot_iteration(settings) -> None:
    with SessionLocal() as db:
        if get_autopilot_enabled(db, settings):
            run_agent_autopilot_cycle(db, settings)
            mark_dashboard_state_updated('autopilot-cycle')


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    migrate_legacy_schema(engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        bootstrap_database(db, settings)
    mark_dashboard_state_updated('startup')

    async def autopilot_loop() -> None:
        interval_seconds = max(30, settings.agent_autopilot_interval_seconds)
        while True:
            try:
                await asyncio.to_thread(_run_autopilot_iteration, settings)
            except Exception as exc:
                error_message = str(exc)
                if _is_broker_auth_failure(error_message):
                    _pause_autopilot_for_broker_failure(error_message)
                    print(f'[agent-autopilot] paused after broker auth failure: {error_message}')
                else:
                    print(f'[agent-autopilot] {error_message}')
            await asyncio.sleep(interval_seconds)

    autopilot_task = asyncio.create_task(autopilot_loop())
    try:
        yield
    finally:
        autopilot_task.cancel()
        with suppress(asyncio.CancelledError):
            await autopilot_task
        close_broker_adapters()


settings = get_settings()
web_dir = Path(__file__).resolve().parent / 'web'

app = FastAPI(title=settings.api_title, version=settings.api_version, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)
app.include_router(router)
app.mount('/static', StaticFiles(directory=web_dir), name='static')


@app.get('/', include_in_schema=False)
@app.get('/app', include_in_schema=False)
def serve_embedded_app() -> FileResponse:
    return FileResponse(web_dir / 'index.html')

@app.get('/favicon.ico', include_in_schema=False)
def serve_favicon() -> FileResponse:
    return FileResponse(web_dir / 'favicon.svg', media_type='image/svg+xml')
