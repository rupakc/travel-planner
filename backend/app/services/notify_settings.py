"""Notification settings: category toggles + daily cap live in ``notify_prefs``;
quiet hours stay in ``alert_prefs.quiet_hours`` (one source of truth, shared
with ``/alerts/preferences``) and are validated by ``alert_delivery``."""

from ..core.config import settings
from ..core.errors import ApiError
from ..db import alerts_db, devices_db, notify_db, user_settings_db
from . import alert_delivery, push

CATEGORIES = (
    "price_drops",
    "trip_reminders",
    "morning_brief",
    "weather",
    "nearby",
    "social",
    "quiz",
)
DEFAULT_CAP = 3
_READ_ONLY = ("timezone", "quiet_hours_active", "push", "devices")


def _invalid(msg: str) -> ApiError:
    return ApiError(422, "notification_settings_invalid", msg)


def apns_configured() -> bool:
    return bool(
        settings.apns_team_id
        and settings.apns_key_id
        and settings.apns_bundle_id
        and (settings.apns_key_p8 or settings.apns_key_file)
    )


def stored(user_id: str) -> dict:
    """Prefs merged over the defaults: ``{"categories": {name: bool}, "daily_cap"}``."""
    data = notify_db.get_data(user_id)
    cats = data.get("categories") if isinstance(data.get("categories"), dict) else {}
    cap = data.get("daily_cap")
    return {
        "categories": {c: cats.get(c) is not False for c in CATEGORIES},
        "daily_cap": cap
        if isinstance(cap, int) and not isinstance(cap, bool) and 1 <= cap <= 10
        else DEFAULT_CAP,
    }


def category_enabled(user_id: str, category: str) -> bool:
    return stored(user_id)["categories"].get(category, True)


def validate(patch: dict) -> dict:
    """Validate a partial update; returns ``{"categories", "daily_cap",
    "quiet_hours"}`` (only the keys present). Read-only keys are ignored."""
    if not isinstance(patch, dict):
        raise _invalid("Body must be an object")
    out: dict = {}
    for key, v in patch.items():
        if key in _READ_ONLY:
            continue
        if key == "categories":
            if not isinstance(v, dict):
                raise _invalid("categories must be an object")
            cats: dict = {}
            for name, c in v.items():
                if name not in CATEGORIES:
                    raise _invalid(f"Unknown category: {name}")
                if (
                    not isinstance(c, dict)
                    or set(c) - {"enabled"}
                    or not isinstance(c.get("enabled"), bool)
                ):
                    raise _invalid(f"categories.{name} must be {{enabled: bool}}")
                cats[name] = c["enabled"]
            out[key] = cats
        elif key == "daily_cap":
            if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 10:
                raise _invalid("daily_cap must be an integer from 1 to 10")
            out[key] = v
        elif key == "quiet_hours":
            try:
                out[key] = alert_delivery.validate_prefs({"quiet_hours": v})[key]
            except ApiError as e:
                raise _invalid(str(e)) from e
        else:
            raise _invalid(f"Unknown setting: {key}")
    return out


def update(user: dict, patch: dict) -> dict:
    clean = validate(patch)
    uid = user["id"]
    if "categories" in clean or "daily_cap" in clean:
        cur = stored(uid)
        cats = {**cur["categories"], **clean.get("categories", {})}
        notify_db.put_data(
            uid,
            {"categories": cats, "daily_cap": clean.get("daily_cap", cur["daily_cap"])},
        )
    if "quiet_hours" in clean:
        merged = alert_delivery.merge_prefs(
            alerts_db.get_prefs(uid), {"quiet_hours": clean["quiet_hours"]}
        )
        alerts_db.put_prefs(uid, merged)
    return view(user)


def view(user: dict) -> dict:
    uid = user["id"]
    cur = stored(uid)
    prefs = alerts_db.get_prefs(uid)
    tz = user_settings_db.get_settings(uid).get("timezone")
    tz = tz if alert_delivery._zone(tz) else None
    return {
        "categories": {c: {"enabled": on} for c, on in cur["categories"].items()},
        "quiet_hours": prefs["quiet_hours"],
        "daily_cap": cur["daily_cap"],
        "timezone": tz,
        "quiet_hours_active": alert_delivery.quiet_active(prefs, tz),
        "push": {"fcm": push.configured(), "apns": apns_configured()},
        "devices": len(devices_db.list_devices(user["username"])),
    }
