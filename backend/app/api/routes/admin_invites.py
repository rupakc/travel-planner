"""Admin-only invite codes (SIGNUP_MODE=invite)."""

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ...core.auth import require_admin
from ...core.errors import ApiError
from ...db import invites_db

router = APIRouter()


class CreateInviteRequest(BaseModel):
    max_uses: int = Field(1, ge=1, le=1000)
    expires_in_days: int = Field(14, ge=1, le=365)
    note: str | None = Field(None, max_length=80)


@router.post("/admin/invites", status_code=201)
def create_invite(body: CreateInviteRequest, admin: dict = Depends(require_admin)):
    return invites_db.create_invite(
        admin.get("username"), body.max_uses, body.expires_in_days, body.note
    )


@router.get("/admin/invites")
def list_invites(_admin: dict = Depends(require_admin)):
    return invites_db.list_invites()


@router.delete("/admin/invites/{invite_id}", status_code=204)
def revoke_invite(invite_id: int, _admin: dict = Depends(require_admin)):
    if not invites_db.revoke_invite(invite_id):
        raise ApiError(404, "not_found", "Invite not found")
    return Response(status_code=204)
