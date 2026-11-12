"""Price alerts 2.0 routes (``/api/alerts/*``). Contract: docs/Alerts-API.md.
Each later task adds its own routes here."""

from fastapi import APIRouter, Body, Depends

from ...core.auth import get_current_user
from ...db import alerts_db, user_settings_db
from ...services import alert_delivery

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
