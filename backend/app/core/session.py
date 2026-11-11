"""Issue the contract ``Session``: access JWT (+ refresh token for mobile)."""

from typing import Literal

from .auth import ACCESS_TOKEN_EXPIRE_HOURS, create_access_token
from .config import settings
from .session_payload import user_payload

Client = Literal["web", "ios", "android"]
MOBILE_CLIENTS = ("ios", "android")


def is_mobile(client: str | None) -> bool:
    return client in MOBILE_CLIENTS


def access_token_for(user: dict, client: str = "web") -> dict:
    """``{"access_token", "token_type", "expires_in"}`` for ``user`` at its
    current token_version. Mobile access tokens are short-lived."""
    minutes = (
        settings.mobile_access_token_minutes
        if is_mobile(client)
        else ACCESS_TOKEN_EXPIRE_HOURS * 60
    )
    token = create_access_token(
        {
            "sub": user["username"],
            "uid": user["id"],
            "tv": int(user.get("token_version") or 0),
            "is_admin": bool(user.get("is_admin")),
            "is_first_login": bool(user.get("is_first_login")),
        },
        minutes=minutes,
    )
    return {"access_token": token, "token_type": "bearer", "expires_in": minutes * 60}


def session_tokens(
    user: dict, client: str = "web", device_name: str | None = None
) -> dict:
    """Access token, plus a new refresh-token family for mobile clients."""
    from ..db.sessions_db import create_refresh

    out = access_token_for(user, client)
    if is_mobile(client):
        out["refresh_token"] = create_refresh(
            user["id"], client, device_name, int(user.get("token_version") or 0)
        )
    return out


def issue_session(
    user: dict, client: str = "web", device_name: str | None = None
) -> dict:
    """The contract ``Session``; records the sign-in time."""
    from ..db.users_db import touch_last_login

    out = session_tokens(user, client, device_name)
    out["user"] = user_payload(user)
    touch_last_login(user["id"])
    return out


def email_hint(email: str | None) -> str | None:
    """``jane@example.com`` → ``j•••@example.com``."""
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}•••@{domain}"
