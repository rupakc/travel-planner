"""Admin moderation for the social feed (Phase 5). Contract: Social-API.md."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from ...core.auth import require_admin
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...db import social_db
from ...db import social_ideas_db as db
from .social import require_enabled

_EXCERPT = 120
inner = APIRouter(dependencies=[Depends(rate_limit("admin"))])
router = APIRouter(dependencies=[Depends(require_enabled)])


@inner.get("/admin/social/queue")
def queue(
    status: Literal["held", "reported", "hidden"] = "held",
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    _admin: dict = Depends(require_admin),
):
    try:
        offset = int(cursor) if cursor else 0
    except ValueError:
        raise ApiError(422, "invalid_cursor", "Bad cursor.") from None
    rows = db.queue(status)
    page = rows[offset : offset + limit]
    items = []
    for r in page:
        ref = r.pop("_ref")
        r["excerpt"] = (r["excerpt"] or "")[:_EXCERPT]
        r["reason_counts"] = db.reason_counts(r["target"], ref)
        items.append(r)
    more = offset + limit < len(rows)
    return {"items": items, "next": str(offset + limit) if more else None}


class DecideBody(BaseModel):
    action: Literal["approve", "remove"]


@inner.post("/admin/social/{target}/{item_id}/decide")
def decide(
    target: Literal["idea", "comment", "profile"],
    item_id: str,
    body: DecideBody,
    _admin: dict = Depends(require_admin),
):
    nf = ApiError(404, "not_found", "Nothing to decide.")
    if target == "profile":
        p = social_db.get_profile_by_handle(item_id)
        if not p:
            raise nf
        if body.action == "remove":
            # Private, bio and avatar opt-in cleared so the owner cannot
            # republish the same bio straight away.
            social_db.save_profile(
                p["user_id"],
                {"visibility": "private", "bio": "", "show_avatar": False},
            )
        db.resolve_reports("profile", p["user_id"])
        return {"target": target, "id": item_id, "status": body.action}
    if not item_id.isdigit():
        raise nf
    n = int(item_id)
    exists = db.get_idea_raw(n) if target == "idea" else db.get_comment(n)
    if not exists:
        raise nf
    status = "published" if body.action == "approve" else "removed"
    db.set_status("ideas" if target == "idea" else "comments", n, status)
    db.resolve_reports(target, item_id)
    return {"target": target, "id": item_id, "status": status}


class RestrictBody(BaseModel):
    days: int = Field(..., ge=1, le=365)


def _uid(handle: str) -> str:
    p = social_db.get_profile_by_handle(handle)
    if not p:
        raise ApiError(404, "profile_not_found", "Profile not found.")
    return p["user_id"]


@inner.post("/admin/social/users/{handle}/restrict")
def restrict(handle: str, body: RestrictBody, _admin: dict = Depends(require_admin)):
    return {"until": db.restrict(_uid(handle), body.days)}


@inner.delete("/admin/social/users/{handle}/restrict", status_code=204)
def lift(handle: str, _admin: dict = Depends(require_admin)):
    db.lift(_uid(handle))
    return Response(status_code=204)


router.include_router(inner)
