import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes import (
    activities,
    flights,
    forex,
    getting_around,
    hotels,
    itinerary,
    search,
    sim,
    tips,
    visa,
)
from .api.routes.admin import router as admin_router
from .api.routes.airports import router as airports_router
from .api.routes.analytics import router as analytics_router
from .api.routes.auth import router as auth_router
from .api.routes.chat import router as chat_router
from .api.routes.discover import router as discover_router
from .api.routes.events import router as events_router
from .api.routes.feedback import router as feedback_router
from .api.routes.nationalities import router as nationalities_router
from .api.routes.plans import router as plans_router
from .api.routes.preferences import router as preferences_router
from .api.routes.stress_test import router as stress_test_router
from .api.routes.taste import router as taste_router
from .core.config import settings as _settings
from .core.logging_config import configure_logging
from .db.backup import backup_to_gcs, restore_from_gcs, start_periodic_backup
from .db.database import create_tables
from .db.plans_db import create_plans_table
from .db.preferences_db import create_preferences_table
from .db.seed_airports import seed as seed_airports
from .db.seed_nationalities import seed as seed_nationalities
from .middleware.analytics import AnalyticsMiddleware
from .middleware.request_id import RequestIdMiddleware
from .services.activity_url_resolver import close_client as _close_activity_client
from .services.serp_flights import close_client as _close_serp_client

configure_logging(json_logs=os.getenv("LOG_FORMAT", "json") == "json")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await restore_from_gcs(_settings.backup_bucket, _settings.data_dir)
    seed_airports()
    seed_nationalities()
    create_tables()
    create_plans_table()
    create_preferences_table()
    from .db.feedback_db import create_feedback_table
    from .db.taste_db import create_taste_table
    from .db.users_db import create_users_table, seed_admin

    create_users_table()
    seed_admin()
    create_feedback_table()
    create_taste_table()
    asyncio.create_task(
        start_periodic_backup(
            _settings.backup_bucket, _settings.data_dir, interval_seconds=60
        )
    )
    yield
    # SIGTERM: force=True always uploads our current state regardless of GCS generation.
    # This is safe — the dying instance holds the most up-to-date data.
    await backup_to_gcs(_settings.backup_bucket, _settings.data_dir, force=True)
    await _close_serp_client()
    await _close_activity_client()


app = FastAPI(
    title="Travel Planner API",
    description="AI-powered travel planning with multi-agent architecture",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AnalyticsMiddleware)
app.add_middleware(RequestIdMiddleware)


app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(feedback_router, prefix="/api", tags=["feedback"])
app.include_router(analytics_router, prefix="/api", tags=["analytics"])
app.include_router(chat_router, prefix="/api", tags=["chat"])
app.include_router(plans_router, prefix="/api", tags=["plans"])
app.include_router(preferences_router, prefix="/api", tags=["preferences"])
app.include_router(airports_router, prefix="/api", tags=["airports"])
app.include_router(nationalities_router, prefix="/api", tags=["nationalities"])
app.include_router(search.router, prefix="/api", tags=["search"])
app.include_router(flights.router, prefix="/api", tags=["flights"])
app.include_router(hotels.router, prefix="/api", tags=["hotels"])
app.include_router(activities.router, prefix="/api", tags=["activities"])
app.include_router(visa.router, prefix="/api", tags=["visa"])
app.include_router(sim.router, prefix="/api", tags=["sim"])
app.include_router(tips.router, prefix="/api", tags=["tips"])
app.include_router(getting_around.router, prefix="/api", tags=["getting_around"])
app.include_router(forex.router, prefix="/api", tags=["forex"])
app.include_router(itinerary.router, prefix="/api", tags=["itinerary"])
app.include_router(discover_router, prefix="/api", tags=["discover"])
app.include_router(stress_test_router, prefix="/api", tags=["stress_test"])
app.include_router(taste_router, prefix="/api", tags=["taste"])
app.include_router(events_router, prefix="/api", tags=["events"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "travel-planner-backend"}
