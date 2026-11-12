"""Notification settings + text catalog. Contract: docs/Notifications-API.md."""

from fastapi import APIRouter, Body, Depends, Query

from ...core.auth import get_current_user
from ...services import notify_settings, notify_text

router = APIRouter()


@router.get("/notification-settings")
def get_notification_settings(user: dict = Depends(get_current_user)):
    return notify_settings.view(user)


@router.put("/notification-settings")
def put_notification_settings(
    body: dict = Body(...), user: dict = Depends(get_current_user)
):
    return notify_settings.update(user, body)


@router.get("/notifications/catalog")
def notification_catalog(
    locale: str | None = Query(None, max_length=35),
    user: dict = Depends(get_current_user),
):
    return notify_text.catalog(locale)
