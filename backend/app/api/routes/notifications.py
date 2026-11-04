"""In-app notifications (fare alerts and fare-watch status) for the bell."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...db import notifications_db
from ...services.fare_watch import utcnow

router = APIRouter()


class MarkRead(BaseModel):
    ids: list[int] | None = Field(None, max_length=500)
    all: bool = False


@router.get("/notifications")
def list_notifications(
    unread_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    page = notifications_db.list_notifications(
        user["id"], unread_only=unread_only, limit=limit, offset=offset
    )
    page["items"] = [
        {k: v for k, v in n.items() if k != "user_id"} for n in page["items"]
    ]
    page["unread"] = notifications_db.count_unread(user["id"])
    return page


@router.get("/notifications/unread-count")
def unread_count(user: dict = Depends(get_current_user)):
    return {"count": notifications_db.count_unread(user["id"])}


@router.post("/notifications/read")
def mark_read(body: MarkRead, user: dict = Depends(get_current_user)):
    if not body.all and body.ids is None:
        raise HTTPException(status_code=422, detail="Pass ids or all=true")
    updated = notifications_db.mark_read(
        user["id"], None if body.all else body.ids, now=utcnow()
    )
    return {"updated": updated, "unread": notifications_db.count_unread(user["id"])}
