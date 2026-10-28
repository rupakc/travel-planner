from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints, model_validator

from ...core.auth import get_current_user
from ...db.recent_searches_db import (
    delete_recent_search,
    list_recent_searches,
    record_search,
)

router = APIRouter()

_Tag = Annotated[str, StringConstraints(max_length=100)]


class RecentStop(BaseModel):
    city: str = Field(min_length=1, max_length=200)
    nights: int | None = Field(None, ge=1, le=30)


class RecentSearchIn(BaseModel):
    """The Search form as the user submitted it — enough to refill it later."""

    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    departure_date: date
    return_date: date | None = None
    stops: list[RecentStop] = Field(default_factory=list, max_length=3)
    nationality: str = Field("", max_length=200)
    residence_permits: list[_Tag] = Field(default_factory=list, max_length=20)
    existing_visas: list[_Tag] = Field(default_factory=list, max_length=20)
    interests: list[_Tag] = Field(default_factory=list, max_length=20)
    budget_usd: float | None = Field(None, ge=0)
    adults: int = Field(1, ge=0, le=20)
    children: int = Field(0, ge=0, le=20)
    seniors: int = Field(0, ge=0, le=20)
    infants: int = Field(0, ge=0, le=20)
    accessibility_needs: list[_Tag] = Field(default_factory=list, max_length=20)
    serendipity: float = Field(0.5, ge=0, le=1)

    @model_validator(mode="after")
    def _return_not_before_departure(self):
        if self.return_date and self.return_date < self.departure_date:
            raise ValueError("return_date must not be before departure_date")
        return self


@router.get("/recent-searches")
def get_recent_searches(user: dict = Depends(get_current_user)):
    """The current user's recent searches, most recent first."""
    return list_recent_searches(user["username"])


@router.post("/recent-searches")
def save_recent_search(
    search: RecentSearchIn,
    user: dict = Depends(get_current_user),
):
    """Remember a submitted search; an identical one moves back to the top."""
    return record_search(user["username"], search.model_dump(mode="json"))


@router.delete("/recent-searches/{search_id}", status_code=204)
def remove_recent_search(search_id: str, user: dict = Depends(get_current_user)):
    if not delete_recent_search(user["username"], search_id):
        raise HTTPException(status_code=404, detail="Recent search not found")
    return Response(status_code=204)
