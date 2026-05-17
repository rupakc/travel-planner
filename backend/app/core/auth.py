from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

from .config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

_bearer = HTTPBearer(auto_error=False)


def _secret() -> str:
    return settings.jwt_secret_key


def create_access_token(data: dict) -> str:
    """Create a JWT. Pass at minimum {"sub": username}; extra claims are included."""
    payload = {**data, "exp": datetime.now(timezone.utc) + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)}
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and return JWT payload, or raise HTTPException 401."""
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """Validate JWT and return user row from DB. Raises 401 if missing/invalid/inactive."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    username: str = payload.get("sub", "")
    from ..db.users_db import get_user_by_username
    user = get_user_by_username(username)
    if not user or not user.get("is_active"):
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising 401."""
    if not credentials:
        return None
    try:
        payload = jwt.decode(credentials.credentials, _secret(), algorithms=[ALGORITHM])
        username = payload.get("sub", "")
        from ..db.users_db import get_user_by_username
        return get_user_by_username(username)
    except JWTError:
        return None


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Dependency that ensures the current user is an admin."""
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
