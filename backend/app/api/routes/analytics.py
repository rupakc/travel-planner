"""Frontend analytics event ingestion — logs to stdout → Cloud Logging."""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...core.auth import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


class AnalyticsEvent(BaseModel):
    feature: str = Field(..., max_length=64)
    page: str = Field(..., max_length=64)
    metadata: dict[str, Any] | None = None
    ts: int | None = None


class AnalyticsBatch(BaseModel):
    events: list[AnalyticsEvent] = Field(..., max_length=50)


@router.post("/analytics/events", status_code=204)
async def ingest_events(
    batch: AnalyticsBatch,
    current_user: dict = Depends(get_current_user),
):
    username = current_user["username"]
    for ev in batch.events:
        logger.info(
            json.dumps(
                {
                    "event": "feature_used",
                    "feature": ev.feature,
                    "page": ev.page,
                    "user": username,
                    "metadata": ev.metadata or {},
                    "ts": ev.ts,
                }
            )
        )
