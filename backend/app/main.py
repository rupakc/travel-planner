import asyncio
import logging
import os
import tempfile
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
from .api.routes.account import router as account_router
from .api.routes.account_data import router as account_data_router
from .api.routes.admin import router as admin_router
from .api.routes.admin_invites import router as admin_invites_router
from .api.routes.airports import router as airports_router
from .api.routes.alerts import router as alerts_router
from .api.routes.analytics import router as analytics_router
from .api.routes.auth import router as auth_router
from .api.routes.avatars import router as avatars_router
from .api.routes.chat import router as chat_router
from .api.routes.client_config import router as client_config_router
from .api.routes.compare import router as compare_router
from .api.routes.devices import router as devices_router
from .api.routes.discover import router as discover_router
from .api.routes.events import router as events_router
from .api.routes.fare_watches import router as fare_watches_router
from .api.routes.feedback import router as feedback_router
from .api.routes.game import router as game_router
from .api.routes.layover import router as layover_router
from .api.routes.link_import import router as link_import_router
from .api.routes.live_check import router as live_check_router
from .api.routes.nationalities import router as nationalities_router
from .api.routes.nearby import router as nearby_router
from .api.routes.notifications import router as notifications_router
from .api.routes.oauth import router as oauth_router
from .api.routes.plans import router as plans_router
from .api.routes.preferences import router as preferences_router
from .api.routes.price_watches import router as price_watches_router
from .api.routes.quota import router as quota_router
from .api.routes.recent_searches import router as recent_searches_router
from .api.routes.sessions import router as sessions_router
from .api.routes.shares import public_router as shares_public_router
from .api.routes.shares import router as shares_router
from .api.routes.signup import router as signup_router
from .api.routes.stress_test import router as stress_test_router
from .api.routes.taste import router as taste_router
from .api.routes.telemetry import router as telemetry_router
from .api.routes.trip_journal import router as trip_journal_router
from .api.routes.trip_money import router as trip_money_router
from .api.routes.trip_offline import router as trip_offline_router
from .api.routes.trip_prep import router as trip_prep_router
from .api.routes.trip_recap import router as trip_recap_router
from .api.routes.trip_today import router as trip_today_router
from .api.routes.trips import router as trips_router
from .api.routes.walking_tours import router as walking_tours_router
from .core import sse as _sse
from .core.ai_quota import daily_quota
from .core.body_limit import BodySizeLimit
from .core.config import settings as _settings
from .core.errors import ApiError
from .core.logging_config import configure_logging
from .core.rate_limit import rate_limit, require_ai_access
from .db import vm_backup
from .db.backup import backup_to_gcs, restore_from_gcs, start_periodic_backup
from .db.database import create_tables
from .db.plans_db import create_plans_table
from .db.preferences_db import create_preferences_table
from .db.recent_searches_db import create_recent_searches_table
from .db.seed_airports import seed as seed_airports
from .db.seed_nationalities import seed as seed_nationalities
from .middleware.analytics import AnalyticsMiddleware
from .middleware.request_id import RequestIdMiddleware
from .services import alert_delivery, fare_watch, price_watch, push
from .services.account_maintenance import account_maintenance
from .services.activity_url_resolver import close_client as _close_activity_client
from .services.serp_flights import close_client as _close_serp_client
from .telemetry.maintenance import telemetry_maintenance

configure_logging(json_logs=os.getenv("LOG_FORMAT", "json") == "json")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    vm_mode = _settings.backup_mode == "vm"
    export_dir = _settings.backup_export_dir or tempfile.gettempdir()
    if vm_mode:
        # The disk is authoritative: guard + restore only if the DB is missing.
        # Raises (refuses to start) rather than run on the wrong directory.
        await vm_backup.startup(_settings.backup_bucket, _settings.data_dir)
    else:
        await restore_from_gcs(_settings.backup_bucket, _settings.data_dir)
    seed_airports()
    from .db.places_db import warm as warm_place_index

    warm_place_index()  # airport-name index, built once from the seeded DB
    seed_nationalities()
    create_tables()
    create_plans_table()
    create_preferences_table()
    create_recent_searches_table()
    from .db.accounts_schema import create_account_tables
    from .db.feedback_db import create_feedback_table
    from .db.taste_db import create_taste_table
    from .db.trips_schema import create_trip_tables
    from .db.users_db import create_users_table, seed_admin

    create_users_table()
    create_account_tables()
    create_trip_tables()  # ALTERs plans: after create_plans_table()
    seed_admin()
    create_feedback_table()
    create_taste_table()
    from .db import telemetry_db
    from .db.alerts_db import create_alert_tables
    from .db.devices_db import create_devices_table
    from .db.fare_watch_db import create_fare_watch_tables
    from .db.notifications_db import create_notifications_table
    from .db.price_watch_db import create_price_watch_tables
    from .db.shares_db import create_shares_table

    create_fare_watch_tables()
    create_price_watch_tables()
    create_alert_tables()
    create_shares_table()
    create_notifications_table()
    create_devices_table()
    # telemetry.db is disposable (not backed up): if it can't be opened, log
    # and run with telemetry off rather than refuse to start
    try:
        telemetry_db.create_telemetry_tables()
        telemetry_db.set_available(True)
    except Exception:
        logger.exception("telemetry store unavailable; telemetry disabled")
        telemetry_db.set_available(False)
    price_watch.register_builtin_sources()
    from .core import llm

    # Resolves LLM_PROVIDER=auto once and logs it; a thinking level the Gemini
    # model rejects stops startup here instead of failing every call
    llm.log_provider()
    # Fare- and price-watch re-checks (one loop): only with live fares (SERPAPI_KEY) and
    # FARE_WATCH_ENABLED. Single-worker deployments — see Deployment.md.
    fare_watch_task = fare_watch.start_scheduler()
    alert_delivery_task = alert_delivery.start_loop()
    telemetry_task = (
        asyncio.create_task(telemetry_maintenance())
        if telemetry_db.store_available()
        else None
    )
    account_task = asyncio.create_task(account_maintenance())
    if vm_mode:
        backup_task = vm_backup.start(
            _settings.backup_bucket,
            _settings.data_dir,
            export_dir,
            _settings.backup_interval_seconds,
        )
    else:
        backup_task = asyncio.create_task(
            start_periodic_backup(
                _settings.backup_bucket, _settings.data_dir, interval_seconds=60
            )
        )
    yield
    account_task.cancel()
    try:
        await account_task
    except asyncio.CancelledError:
        pass
    if telemetry_task is not None:
        telemetry_task.cancel()
        try:
            await telemetry_task
        except asyncio.CancelledError:
            pass
    await fare_watch.stop_scheduler(fare_watch_task)
    await alert_delivery.stop_loop(alert_delivery_task)
    await llm.aclose()
    await push.drain()  # pushes in flight: a few seconds, then cancelled
    if vm_mode:
        # Clean shutdown: one more export, uploaded only if it changed
        await vm_backup.stop(
            backup_task, _settings.backup_bucket, _settings.data_dir, export_dir
        )
    else:
        # SIGTERM: force=True always uploads our current state regardless of GCS
        # generation. Safe: the dying instance holds the most up-to-date data.
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

# Plan-from-a-link bodies carry screenshots (4 × ≤5 MB base64); refuse anything
# bigger (declared or streamed) before FastAPI reads and parses it. Keep in step
# with nginx's client_max_body_size (frontend/nginx.conf.template).
app.add_middleware(
    BodySizeLimit,
    prefix="/api/import/",
    max_bytes=30 * 1024 * 1024,
    message="That upload is too big — use up to 4 screenshots of 5 MB or less.",
)


app.add_middleware(
    BodySizeLimit,
    prefix="/api/account/avatar",
    max_bytes=2 * 1024 * 1024 + 64 * 1024,
    message="That image is too big — use one under 2 MB.",
    error_code="avatar_too_large",
)

app.add_middleware(RequestIdMiddleware)


@app.exception_handler(ApiError)
async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(exc.body(), status_code=exc.status, headers=exc.headers)


def _limited(bucket: str) -> list:
    """Router dependencies for AI routes: sign-in when ALLOW_ANONYMOUS_AI is
    false, then one rate-limit bucket for every route."""
    return [
        Depends(require_ai_access),
        Depends(rate_limit(bucket)),
        Depends(daily_quota(bucket)),
    ]


# Every route on the routers marked _limited(...) calls an LLM; see
# app/core/rate_limit.py and the rate_limit_* settings.
app.include_router(auth_router, prefix="/api", tags=["auth"])
app.include_router(signup_router, prefix="/api", tags=["signup"])
app.include_router(sessions_router, prefix="/api", tags=["sessions"])
app.include_router(oauth_router, prefix="/api", tags=["oauth"])
app.include_router(account_router, prefix="/api", tags=["account"])
app.include_router(avatars_router, prefix="/api", tags=["avatars"])
app.include_router(account_data_router, prefix="/api", tags=["account_data"])
app.include_router(game_router, prefix="/api", tags=["game"])
app.include_router(quota_router, prefix="/api", tags=["quota"])
app.include_router(admin_invites_router, prefix="/api", tags=["admin_invites"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(feedback_router, prefix="/api", tags=["feedback"])
app.include_router(analytics_router, prefix="/api", tags=["analytics"])
# Product telemetry: anonymous-friendly, its own bucket, never behind require_ai_access
app.include_router(
    telemetry_router,
    prefix="/api",
    tags=["telemetry"],
    dependencies=[Depends(rate_limit("telemetry"))],
)
app.include_router(client_config_router, prefix="/api", tags=["config"])
app.include_router(
    chat_router, prefix="/api", tags=["chat"], dependencies=_limited("chat")
)
app.include_router(plans_router, prefix="/api", tags=["plans"])
app.include_router(trips_router, prefix="/api", tags=["trips"])
app.include_router(trip_prep_router, prefix="/api", tags=["trips"])
app.include_router(trip_money_router, prefix="/api", tags=["trips"])
app.include_router(trip_journal_router, prefix="/api", tags=["trips"])
app.include_router(trip_offline_router, prefix="/api", tags=["trips"])
app.include_router(trip_today_router, prefix="/api", tags=["trips"])
app.include_router(trip_recap_router, prefix="/api", tags=["trips"])
app.include_router(preferences_router, prefix="/api", tags=["preferences"])
app.include_router(recent_searches_router, prefix="/api", tags=["recent_searches"])
app.include_router(airports_router, prefix="/api", tags=["airports"])
app.include_router(nationalities_router, prefix="/api", tags=["nationalities"])
app.include_router(
    search.router, prefix="/api", tags=["search"], dependencies=_limited("search")
)
app.include_router(
    flights.router, prefix="/api", tags=["flights"], dependencies=_limited("light_ai")
)
app.include_router(
    hotels.router, prefix="/api", tags=["hotels"], dependencies=_limited("light_ai")
)
app.include_router(
    activities.router,
    prefix="/api",
    tags=["activities"],
    dependencies=_limited("light_ai"),
)
app.include_router(
    visa.router, prefix="/api", tags=["visa"], dependencies=_limited("light_ai")
)
app.include_router(
    sim.router, prefix="/api", tags=["sim"], dependencies=_limited("light_ai")
)
app.include_router(
    tips.router, prefix="/api", tags=["tips"], dependencies=_limited("light_ai")
)
app.include_router(
    getting_around.router,
    prefix="/api",
    tags=["getting_around"],
    dependencies=_limited("light_ai"),
)
app.include_router(
    forex.router, prefix="/api", tags=["forex"], dependencies=_limited("light_ai")
)
app.include_router(
    itinerary.router,
    prefix="/api",
    tags=["itinerary"],
    dependencies=_limited("light_ai"),
)
app.include_router(
    discover_router, prefix="/api", tags=["discover"], dependencies=_limited("discover")
)
app.include_router(
    compare_router, prefix="/api", tags=["compare"], dependencies=_limited("compare")
)
app.include_router(
    stress_test_router,
    prefix="/api",
    tags=["stress_test"],
    dependencies=_limited("light_ai"),
)
app.include_router(taste_router, prefix="/api", tags=["taste"])
# Fare watches: create and "check now" draw on the light_ai bucket (per route)
app.include_router(fare_watches_router, prefix="/api", tags=["fare_watches"])
app.include_router(price_watches_router, prefix="/api", tags=["price_watches"])
app.include_router(alerts_router, prefix="/api", tags=["alerts"])
app.include_router(
    shares_router,
    prefix="/api",
    tags=["shares"],
    dependencies=[Depends(rate_limit("share_manage"))],
)
app.include_router(
    shares_public_router,
    prefix="/api",
    tags=["shares"],
    dependencies=[Depends(rate_limit("share_public"))],
)
app.include_router(notifications_router, prefix="/api", tags=["notifications"])
app.include_router(devices_router, prefix="/api", tags=["devices"])
app.include_router(
    nearby_router, prefix="/api", tags=["nearby"], dependencies=_limited("light_ai")
)
app.include_router(
    live_check_router,
    prefix="/api",
    tags=["live_check"],
    dependencies=_limited("light_ai"),
)
app.include_router(
    events_router, prefix="/api", tags=["events"], dependencies=_limited("light_ai")
)
app.include_router(
    walking_tours_router,
    prefix="/api",
    tags=["walking_tours"],
    dependencies=_limited("light_ai"),
)
app.include_router(
    layover_router, prefix="/api", tags=["layover"], dependencies=_limited("light_ai")
)
app.include_router(
    link_import_router,
    prefix="/api",
    tags=["import"],
    dependencies=_limited("import"),
)


@app.get("/health/agents")
async def health_agents():
    """Deep health: verifies the LLM pipeline actually works from this
    instance (one tiny call to the configured provider, cached 5 min so it
    can't be abused). Lets operators distinguish 'backend up' from 'agents
    can run'."""
    from .core import llm as llm_client
    from .core.cache import get_cache

    cache = get_cache()
    cached = cache.get("health:agents")
    if cached:
        return cached
    try:
        resp = await llm_client.generate(
            [{"role": "user", "content": "Reply with the word OK"}],
            max_tokens=8,
            label="health",
            timeout=15,
            retries=False,
        )
        llm = "ok" if resp.text else "empty-response"
    except llm_client.LLMError as e:
        llm = {
            llm_client.SPEND_CAP_CODE: "spend-cap",
            llm_client.BILLING_CODE: "billing-disabled",
        }.get(e.user_code) or f"error: {type(e.__cause__ or e).__name__}"
    result = {
        "llm": llm,
        "llm_provider": llm_client.provider(),
        "llm_provider_reason": llm_client.provider_reason(),
        "serpapi_configured": bool(_settings.serpapi_key),
        "backup_configured": bool(_settings.backup_bucket),
    }
    cache["health:agents"] = result
    return result


@app.get("/health")
async def health():
    body = {
        "status": "ok",
        "service": "travel-planner-backend",
        # Cheap capability flag: the UI offers the fare calendar only when set
        "serpapi_configured": bool(_settings.serpapi_key),
        # The UI offers "Watch this fare" / the email option only when set
        "fare_watch_available": bool(
            _settings.serpapi_key and _settings.fare_watch_enabled
        ),
        "email_alerts_available": bool(_settings.smtp_host),
        # Alerts also go to registered phones (FCM) only when set
        "push_configured": push.configured(),
    }
    # VM backups: the uptime check content-matches "backup_ok":true
    backup = vm_backup.status()
    if backup is not None:
        body["backup_ok"] = backup["ok"]
        body["backup"] = backup
    return body


# Deployer-only: the VM's deploy.sh asks the app container directly
# (172.30.0.10:8001, compose network) how many SSE streams are open and waits
# for 0 (up to ~90 s) before it recreates Caddy. Not under /api or /health,
# so Caddy never routes it (the SPA catch-all answers instead); a request that
# arrives through a proxy anyway (forwarding headers) gets a plain 404.
# Exposes one number, nothing about who is streaming.
_FORWARDING_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded")


@app.get("/internal/streams", include_in_schema=False)
async def internal_streams(request: Request):
    if any(h in request.headers for h in _FORWARDING_HEADERS):
        raise HTTPException(status_code=404)
    return {"active_streams": _sse.active_streams()}
