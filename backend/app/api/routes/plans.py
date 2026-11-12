import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...core.auth import get_current_user
from ...db.plans_db import (
    delete_plan,
    get_plan,
    get_plan_by_share_token,
    get_user_plans,
    save_plan,
    set_share_token,
    update_plan,
)
from ...db.taste_db import record_plan_signals
from ...game import trip_hooks

logger = logging.getLogger(__name__)

router = APIRouter()

# search_data fields safe to expose on a public share link.
# Personal fields (nationality, visas, permits, accessibility) are dropped.
_PUBLIC_SEARCH_FIELDS = (
    "origin",
    "destination",
    "destinations",
    "departure_date",
    "return_date",
    "interests",
    "num_travelers",
    "adults",
    "children",
    "seniors",
    "infants",
    "pace",
)


def _public_import_source(value) -> dict | None:
    """The "Inspired by" link of an imported trip: title and an http(s) URL."""
    if not isinstance(value, dict):
        return None
    url = value.get("url")
    if not (isinstance(url, str) and url.lower().startswith(("http://", "https://"))):
        url = None
    title = value.get("title") if isinstance(value.get("title"), str) else None
    return {"url": url, "title": title}


def _sanitize_shared_plan(plan: dict) -> dict:
    search_data = plan.get("search_data") or {}
    public = {k: v for k, v in search_data.items() if k in _PUBLIC_SEARCH_FIELDS}
    import_source = _public_import_source(search_data.get("import_source"))
    if import_source:
        public["import_source"] = import_source
    return {
        "name": plan.get("name"),
        "created_at": plan.get("created_at"),
        "updated_at": plan.get("updated_at"),
        "search_data": public,
        "selections": plan.get("selections") or {},
    }


class SavePlanRequest(BaseModel):
    name: str
    search_data: dict
    selections: dict


class UpdatePlanRequest(BaseModel):
    name: str | None = None
    selections: dict | None = None


@router.get("/plans")
def list_plans(current_user: dict = Depends(get_current_user)):
    return get_user_plans(current_user["username"])


@router.post("/plans")
def create_plan(req: SavePlanRequest, current_user: dict = Depends(get_current_user)):
    plan = save_plan(
        current_user["username"], req.name, req.search_data, req.selections
    )
    record_plan_signals(current_user["username"], req.search_data, req.selections)
    try:  # the award never blocks the save; the response keys are unchanged
        trip_hooks.on_plan_saved(current_user["id"], plan["id"])
    except Exception as exc:
        logger.warning("plan_saved hook failed (%s)", type(exc).__name__)
    return plan


@router.get("/plans/{plan_id}")
def get_one_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    return plan


@router.put("/plans/{plan_id}")
def update_one_plan(
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


@router.post("/plans/{plan_id}/share")
def share_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Generate (or return the existing) public share token for a plan."""
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    token = plan.get("share_token") or secrets.token_urlsafe(16)
    updated = set_share_token(plan_id, current_user["username"], token)
    return {"share_token": updated["share_token"]}


@router.delete("/plans/{plan_id}/share")
def revoke_share(plan_id: int, current_user: dict = Depends(get_current_user)):
    """Revoke the public share link for a plan."""
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    set_share_token(plan_id, current_user["username"], None)
    return {"success": True}


@router.get("/share/{token}")
def get_shared_plan(token: str):
    """Public, read-only view of a shared plan — no authentication required."""
    plan = get_plan_by_share_token(token)
    if not plan:
        raise HTTPException(status_code=404, detail="Shared plan not found")
    return _sanitize_shared_plan(plan)


@router.delete("/plans/{plan_id}")
def delete_one_plan(plan_id: int, current_user: dict = Depends(get_current_user)):
    plan = get_plan(plan_id)
    if not plan or plan["username"] != current_user["username"]:
        raise HTTPException(status_code=404, detail="Plan not found")
    delete_plan(plan_id, current_user["username"])
    return {"success": True}
