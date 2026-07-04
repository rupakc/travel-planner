from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import get_current_user
from ...db.plans_db import delete_plan, get_plan, get_user_plans, save_plan, update_plan
from ...db.taste_db import record_plan_signals

router = APIRouter()


class SavePlanRequest(BaseModel):
    name: str
    search_data: dict
    selections: dict


class UpdatePlanRequest(BaseModel):
    name: str | None = None
    selections: dict | None = None


@router.get("/plans")
async def list_plans(current_user: dict = Depends(get_current_user)):
    return get_user_plans(current_user["username"])


@router.post("/plans")
async def create_plan(
    req: SavePlanRequest, current_user: dict = Depends(get_current_user)
):
    plan = save_plan(
        current_user["username"], req.name, req.search_data, req.selections
    )
    record_plan_signals(current_user["username"], req.search_data, req.selections)
    return plan


@router.get("/plans/{plan_id}")
async def get_one_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.put("/plans/{plan_id}")
async def update_one_plan(
    plan_id: int, req: UpdatePlanRequest, current_user: dict = Depends(get_current_user)
):
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    updated = update_plan(plan_id, current_user["username"], req.name, req.selections)
    if req.selections is not None:
        record_plan_signals(
            current_user["username"], plan["search_data"], req.selections
        )
    return updated


@router.delete("/plans/{plan_id}")
async def delete_one_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    delete_plan(plan_id, current_user["username"])
    return {"success": True}
