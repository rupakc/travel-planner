"""The contract `User` object."""

from pathlib import Path

from .config import settings
from .urls import public_url


def _avatar_url(user: dict) -> str | None:
    if not user.get("avatar_source"):
        return None
    uid = user["id"]
    if not (Path(settings.data_dir) / "avatars" / f"{uid}.webp").exists():
        return None
    return public_url(f"/api/avatars/{uid}.webp?v={user.get('avatar_rev') or 0}")


def user_payload(user: dict) -> dict:
    signup_method = user.get("signup_method") or "admin"
    return {
        "id": user["id"],
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "email": user.get("email"),
        "email_verified": bool(user.get("email_verified")),
        "is_admin": bool(user.get("is_admin")),
        "requires_password_change": bool(user.get("requires_password_change")),
        "account_verified": signup_method == "admin"
        or user.get("verified_at") is not None,
        "has_password": user.get("password_hash") not in (None, "", "!"),
        "signup_method": signup_method,
        "avatar_url": _avatar_url(user),
    }
