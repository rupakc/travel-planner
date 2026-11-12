"""Price alerts 2.0 routes (``/api/alerts/*``). Contract: docs/Alerts-API.md.
Each later task adds its own routes here."""

from fastapi import APIRouter, Body, Depends

from ...core.ai_quota import daily_quota
from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit, require_ai_access
from ...db import alerts_db, fare_watch_db, price_watch_db, user_settings_db, users_db
from ...services import alert_delivery, alert_story

router = APIRouter()


def _prefs_view(user_id: str) -> dict:
    prefs = alerts_db.get_prefs(user_id)
    tz = user_settings_db.get_settings(user_id).get("timezone")
    prefs["timezone"] = tz if alert_delivery._zone(tz) else None
    prefs["quiet_hours_active"] = alert_delivery.quiet_active(prefs, tz)
    return prefs


@router.get("/alerts/preferences")
def get_preferences(user: dict = Depends(get_current_user)):
    return _prefs_view(user["id"])


@router.put("/alerts/preferences")
def put_preferences(body: dict = Body(...), user: dict = Depends(get_current_user)):
    patch = alert_delivery.validate_prefs(body)
    merged = alert_delivery.merge_prefs(alerts_db.get_prefs(user["id"]), patch)
    alerts_db.put_prefs(user["id"], merged)
    return _prefs_view(user["id"])

KINDS = ("flight", "hotel", "activity", "trip")


def _owned(kind: str, watch_id: int, user: dict) -> tuple[dict, list[dict]]:
    if kind not in KINDS:
        raise ApiError(422, "kind_invalid", "That kind of watch doesn't exist.")
    db = fare_watch_db if kind == "flight" else price_watch_db
    watch = db.get_watch_for_user(watch_id, user["id"])
    if watch is None or (kind != "flight" and watch.get("kind") != kind):
        raise ApiError(404, "watch_not_found", "Watch not found.")
    return watch, db.get_history(watch_id)


def _story(kind: str, watch: dict, history: list[dict], user: dict) -> dict:
    story = alert_story.build_story(
        kind,
        watch,
        history,
        live_prices=bool(settings.serpapi_key),
        now=alert_story._utcnow(),
    )
    story["caught"] = alert_story.caught_for(kind, watch["id"], user["id"])
    return story


@router.get("/alerts/watches/{kind}/{watch_id}/story")
async def watch_story(kind: str, watch_id: int, user: dict = Depends(get_current_user)):
    watch, history = _owned(kind, watch_id, user)
    return _story(kind, watch, history, user)


@router.post(
    "/alerts/watches/{kind}/{watch_id}/advice",
    dependencies=[
        Depends(require_ai_access),
        Depends(rate_limit("light_ai")),
        Depends(daily_quota("light_ai")),
    ],
)
async def watch_advice(
    kind: str, watch_id: int, user: dict = Depends(get_current_user)
):
    watch, history = _owned(kind, watch_id, user)
    if kind != "flight":
        raise ApiError(
            422, "advice_unsupported", "Tips are only available for flight watches."
        )
    story = _story(kind, watch, history, user)
    row = users_db.get_user_by_id(user["id"]) or {}
    return await alert_story.advice(watch, story, locale=row.get("locale"))
