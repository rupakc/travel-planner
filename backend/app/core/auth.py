from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError

from .config import settings
from .errors import ApiError

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
MIN_PASSWORD_LENGTH = 8

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return settings.jwt_secret_key


def create_access_token(data: dict, *, minutes: int | None = None) -> str:
    """Create a JWT. Pass at minimum {"sub": username}; extra claims (``uid``,
    ``tv``, ...) are included. ``minutes`` overrides the default 24 h life."""
    now = datetime.now(UTC)
    life = (
        timedelta(minutes=minutes)
        if minutes is not None
        else timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    )
    payload = {**data, "iat": now, "exp": now + life}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and return JWT payload, or raise HTTPException 401."""
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def _session_revoked() -> ApiError:
    return ApiError(
        401, "session_revoked", "Your session has ended. Please sign in again."
    )


def _user_for(payload: dict) -> dict:
    """The live user a decoded token belongs to, or raise.

    Tokens carry ``uid`` (new) or only ``sub`` (old); a missing ``tv`` counts
    as token_version 0. A pending (unverified) account has no session.
    """
    from ..db.users_db import get_user_by_id, get_user_by_username

    uid = payload.get("uid")
    user = get_user_by_id(uid) if uid else get_user_by_username(payload.get("sub", ""))
    if (
        not user
        or not user.get("is_active")
        or user.get("account_status", "active") != "active"
    ):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    try:
        tv = int(payload.get("tv", 0))
    except (TypeError, ValueError):
        raise _session_revoked()
    if tv != int(user.get("token_version") or 0):
        raise _session_revoked()
    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Validate JWT and return user row from DB. Raises 401 if missing/invalid/
    inactive/pending, and ``401 session_revoked`` when the token's version is stale."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_for(decode_token(credentials.credentials))


def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict | None:
    """Like get_current_user but returns None instead of raising 401.

    A deactivated, pending or revoked-session user is treated as anonymous.
    """
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=[ALGORITHM])
        return _user_for(payload)
    except (PyJWTError, HTTPException, ApiError):
        return None


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that ensures the current user is an admin."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
