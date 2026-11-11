"""GET /account/export and DELETE /account (export my data, delete my account)."""

import asyncio
import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field

from ...core.auth import get_current_user
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...core.session_payload import user_payload
from ...db import users_db
from ...services import account_data

router = APIRouter()


def _last_admin() -> ApiError:
    return ApiError(
        409,
        "last_admin",
        "You're the only admin. Make someone else an admin before deleting "
        "your account.",
    )


@router.get("/account/export", dependencies=[Depends(rate_limit("account"))])
def export_account(user: dict = Depends(get_current_user)):
    data = account_data.export_user(user)
    day = datetime.now(UTC).date().isoformat()
    filename = f"voyager-export-{user['username']}-{day}.json"
    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


class DeleteAccountBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    password: str | None = Field(default=None, max_length=1024)
    confirm_username: str | None = Field(default=None, max_length=256)


def _check_delete(body: DeleteAccountBody, user: dict) -> None:
    if user_payload(user)["has_password"]:
        if not body.password or not users_db.authenticate_user(
            user["username"], body.password
        ):
            raise ApiError(403, "password_incorrect", "That password is incorrect.")
    elif (body.confirm_username or "").strip().lower() != user["username"].lower():
        raise ApiError(400, "confirmation_mismatch", "Type your username to confirm.")
    if user.get("is_admin") and users_db.count_active_admins() <= 1:
        raise _last_admin()


@router.delete(
    "/account", status_code=204, dependencies=[Depends(rate_limit("account"))]
)
async def delete_account(
    body: DeleteAccountBody, user: dict = Depends(get_current_user)
):
    # bcrypt and SQLite run in a worker thread: never block the event loop
    await asyncio.to_thread(_check_delete, body, user)
    try:
        await account_data.delete_user(user)
    except account_data.LastAdminError:
        raise _last_admin()
    return Response(status_code=204)
