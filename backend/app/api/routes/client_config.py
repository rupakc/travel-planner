"""Public client configuration (``GET /api/config``)."""

from fastapi import APIRouter, Request, Response

from ...core.config import settings

router = APIRouter()


@router.get("/config")
def client_config(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "max-age=300"
    base = settings.public_base_url.strip().rstrip("/") or str(request.base_url).rstrip(
        "/"
    )
    return {
        "public_base_url": base,
        "telemetry": {
            "enabled": settings.telemetry_enabled,
            "flush_interval_s": 15,
            "max_batch": 50,
        },
        "features": {"telemetry": settings.telemetry_enabled},
    }
