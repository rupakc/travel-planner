"""Public client configuration (``GET /api/config``)."""

from fastapi import APIRouter, Response

from ...core.config import settings
from ...core.passwords import MIN_PASSWORD_LENGTH_V2
from ...core.urls import public_base_url
from ...db.telemetry_db import telemetry_active
from ...services.account_email import email_delivery_available
from ...services.notify_settings import apns_configured

router = APIRouter()


@router.get("/config")
def client_config(response: Response) -> dict:
    response.headers["Cache-Control"] = "max-age=300"
    telemetry = telemetry_active()
    email = email_delivery_available()
    return {
        "public_base_url": public_base_url(),
        "telemetry": {
            "enabled": telemetry,
            "flush_interval_s": 15,
            "max_batch": 50,
        },
        "auth": {
            "signup_mode": settings.signup_mode,
            "signup_available": email and bool(settings.signup_enabled),
            "password_reset_available": email,
            "min_password_length": MIN_PASSWORD_LENGTH_V2,
            "verify_ttl_s": int(settings.account_token_ttl_minutes) * 60,
        },
        "features": {
            "telemetry": telemetry,
            "accounts": True,
            "game": bool(settings.game_enabled),
            "play": 1 if (settings.play_enabled and settings.game_enabled) else 0,
            "trips": True,
            "journey": bool(settings.journey_ui_enabled),
            "offline_pack": bool(settings.offline_pack_enabled),
            "alerts_api": 2,
            "price_alerts_v2": bool(settings.price_alerts_v2_enabled),
            "sharing": 1 if settings.sharing_v2_enabled else 0,
            "social": 1 if settings.social_enabled else 0,
            "play": 1 if settings.play_enabled and settings.game_enabled else 0,
            "notifications_api": 1,
            "notifications_v2": bool(settings.notifications_v2_enabled),
            "apns": apns_configured(),
            "live_prices": bool(settings.serpapi_key),
        },
    }
