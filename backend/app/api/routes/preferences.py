from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...db.preferences_db import get_preferences, save_preferences

router = APIRouter()


class PreferencesUpdate(BaseModel):
    budget_category: str = Field("medium", pattern="^(low|medium|high)$")
    nationality: str = ""
    current_residence: str = ""
    residence_permits: list[str] = Field(default_factory=list)
    existing_visas: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    num_travelers: int = Field(1, ge=1, le=20)


@router.get("/preferences")
async def get_user_preferences(user: dict = Depends(get_current_user)):
    """Get the current user's travel preferences."""
    return get_preferences(user["username"])


@router.put("/preferences")
async def update_user_preferences(
    prefs: PreferencesUpdate,
    user: dict = Depends(get_current_user),
):
    """Update the current user's travel preferences."""
    return save_preferences(user["username"], prefs.model_dump())
