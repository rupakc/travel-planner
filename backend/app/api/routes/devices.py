"""Push-notification devices of the signed-in user (the Android app registers
its FCM token here; see services/push.py)."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...db import devices_db

router = APIRouter()


class RegisterDevice(BaseModel):
    token: str = Field(..., min_length=1, max_length=4096)
    platform: Literal["android"] = "android"
    locale: str | None = Field(None, max_length=35)


@router.post("/devices")
def register_device(body: RegisterDevice, user: dict = Depends(get_current_user)):
    return devices_db.upsert_device(
        user["username"],
        body.token,
        body.platform,
        body.locale,
        now=datetime.now(UTC),
    )


@router.get("/devices")
def list_devices(user: dict = Depends(get_current_user)):
    return {"items": devices_db.list_devices(user["username"])}


@router.delete("/devices/{token}", status_code=204)
def delete_device(token: str, user: dict = Depends(get_current_user)):
    if not devices_db.delete_device(user["username"], token):
        raise HTTPException(status_code=404, detail="Device not found")
    return Response(status_code=204)
