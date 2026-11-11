"""Admin-only user management endpoints."""

import logging
import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from ...core.auth import require_admin
from ...core.errors import ApiError
from ...core.passwords import password_problem
from ...db import sessions_db, telemetry_db
from ...db.users_db import (
    admin_reset_password,
    create_user,
    deactivate_user,
    get_all_users,
    get_user_by_username,
    reactivate_user,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class CreateUserRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    is_admin: bool = False

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v):
        """Coerce empty / whitespace-only strings to None.

        The frontend always sends email: "" when the field is left blank.
        Storing "" violates the UNIQUE constraint on the second such user.
        """
        if isinstance(v, str):
            v = v.strip()
            return v or None
        return v


class ResetPasswordRequest(BaseModel):
    new_password: str


def _check_password(password: str, *, username: str, email: str | None) -> None:
    """Admin-set (temporary or reset) passwords follow the same policy as
    every other password: ``400`` with ``error_code`` and a readable detail."""
    from .auth import PASSWORD_DETAIL

    problem = password_problem(password, username=username, email=email)
    if problem:
        raise ApiError(400, problem, PASSWORD_DETAIL[problem])


@router.get("/admin/telemetry/summary")
def admin_telemetry_summary(
    days: int = Query(30, ge=1, le=90),
    _admin: dict = Depends(require_admin),
):
    """Daily users/sessions/events, top events and top screens."""
    return telemetry_db.summary(days)


@router.post("/admin/users", status_code=201)
def admin_create_user(
    req: CreateUserRequest,
    _admin: dict = Depends(require_admin),
):
    if get_user_by_username(req.username):
        raise HTTPException(status_code=409, detail="Username already exists")
    _check_password(req.password, username=req.username, email=req.email)
    try:
        user = create_user(
            username=req.username,
            password=req.password,
            email=req.email,
            is_admin=req.is_admin,
            is_first_login=True,
        )
    except sqlite3.IntegrityError as exc:
        # Catch any remaining unique-constraint violations (e.g. duplicate email)
        # and surface them as 409 rather than letting FastAPI produce a 500.
        raise HTTPException(
            status_code=409, detail=f"User could not be created: {exc}"
        ) from exc
    return _safe(user)


@router.get("/admin/users")
def admin_list_users(_admin: dict = Depends(require_admin)):
    return [_safe(u) for u in get_all_users()]


@router.delete("/admin/users/{username}", status_code=204)
def admin_deactivate_user(
    username: str,
    admin: dict = Depends(require_admin),
):
    if username == admin["username"]:
        raise HTTPException(
            status_code=400, detail="Cannot deactivate your own account"
        )
    if not get_user_by_username(username):
        raise HTTPException(status_code=404, detail="User not found")
    deactivate_user(username)


@router.post("/admin/users/{username}/reactivate", status_code=200)
def admin_reactivate_user(
    username: str,
    _admin: dict = Depends(require_admin),
):
    if not get_user_by_username(username):
        raise HTTPException(status_code=404, detail="User not found")
    reactivate_user(username)
    return {"status": "reactivated"}


@router.post("/admin/users/{username}/reset-password", status_code=200)
def admin_reset_password_endpoint(
    username: str,
    req: ResetPasswordRequest,
    _admin: dict = Depends(require_admin),
):
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user["is_active"]:
        raise HTTPException(
            status_code=400, detail="Cannot reset password for an inactive user"
        )
    _check_password(req.new_password, username=username, email=user.get("email"))
    admin_reset_password(username, req.new_password)  # also bumps token_version
    sessions_db.revoke_all(user["id"])
    logger.info("Admin '%s' reset password for user '%s'", _admin["username"], username)
    return {"status": "password_reset", "username": username}


def _safe(user: dict) -> dict:
    """Strip password_hash before returning to client."""
    return {k: v for k, v in user.items() if k != "password_hash"}
