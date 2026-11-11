"""Session lifecycle: refresh (mobile), logout, logout everywhere."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session import access_token_for
from ...db import sessions_db
from ...db.users_db import bump_token_version

router = APIRouter()

_REFRESH_DETAIL = {
    "stale": "This session was just refreshed. Use the newest token.",
    "invalid": "Your session has ended. Please sign in again.",
}


def _now() -> datetime:
    return datetime.now(UTC)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., max_length=256)


class LogoutRequest(BaseModel):
    refresh_token: str | None = Field(None, max_length=256)


@router.post("/auth/refresh", dependencies=[Depends(rate_limit("refresh"))])
def refresh(req: RefreshRequest):
    result = sessions_db.rotate_refresh(req.refresh_token, _now())
    if isinstance(result, sessions_db.RefreshError):
        raise ApiError(401, f"refresh_{result.reason}", _REFRESH_DETAIL[result.reason])
    new_token, user = result
    # refresh tokens exist only for mobile clients: a short-lived access token
    out = access_token_for(user, "ios")
    out["refresh_token"] = new_token
    return out


@router.post(
    "/auth/logout", status_code=204, dependencies=[Depends(rate_limit("refresh"))]
)
def logout(req: LogoutRequest | None = None):
    if req and req.refresh_token:
        sessions_db.revoke_family_of(req.refresh_token)
    return Response(status_code=204)


@router.post(
    "/auth/logout-all", status_code=204, dependencies=[Depends(rate_limit("refresh"))]
)
def logout_all(user: dict = Depends(get_current_user)):
    bump_token_version(user["id"])
    sessions_db.revoke_all(user["id"])
    return Response(status_code=204)
