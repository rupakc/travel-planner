"""Push-notification devices of the signed-in user (the Android app registers
its FCM token here; see services/push.py). A token only ever travels in a
request body, never in a URL, so request logs can't carry it."""

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...db import devices_db

router = APIRouter()


class DeviceToken(BaseModel):
    token: str = Field(..., min_length=1, max_length=4096)


class RegisterDevice(DeviceToken):
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


@router.post("/devices/unregister", status_code=204)
def unregister_device(body: DeviceToken, user: dict = Depends(get_current_user)):
    """Sign-out: forget this phone's token. Idempotent; another user's token
    is left alone (same answer)."""
    devices_db.unregister(user["username"], body.token)
    return Response(status_code=204)


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: int, user: dict = Depends(get_current_user)):
    """Remove one of the caller's devices by its id (e.g. a lost phone)."""
    if not devices_db.delete_device(user["username"], device_id):
        raise HTTPException(status_code=404, detail="Device not found")
    return Response(status_code=204)
