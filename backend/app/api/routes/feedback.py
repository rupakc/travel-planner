from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ...core.auth import get_current_user, require_admin
from ...db.feedback_db import submit_feedback, list_feedback

router = APIRouter()


class FeedbackRequest(BaseModel):
    page: str = Field(..., max_length=64)
    rating: int = Field(..., ge=1, le=5)
    category: str = Field(..., pattern=r"^(bug|feature_request|general|praise)$")
    message: str | None = Field(None, max_length=500)
    metadata: dict | None = None


@router.post("/feedback", status_code=201)
async def post_feedback(
    req: FeedbackRequest,
    current_user: dict = Depends(get_current_user),
):
    item = submit_feedback(
        username=current_user["username"],
        page=req.page,
        rating=req.rating,
        category=req.category,
        message=req.message,
        metadata=req.metadata,
    )
    return item


@router.get("/admin/feedback")
async def admin_list_feedback(
    page: str | None = Query(None),
    category: str | None = Query(None),
    min_rating: int | None = Query(None, ge=1, le=5),
    _admin: dict = Depends(require_admin),
):
    return list_feedback(page=page, category=category, min_rating=min_rating)
