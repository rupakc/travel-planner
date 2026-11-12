"""Share links 2.0 (Phase 4): create, list and revoke; public payloads.

``POST/GET/DELETE /api/shares`` need sign-in and the ``share_manage`` bucket
(router dependency in main.py). Every route answers 404 ``sharing_disabled``
while ``SHARING_V2_ENABLED`` is off.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.urls import public_url
from ...db import shares_db, users_db
from ...db.plans_db import get_plan
from ...services import alert_moments, share_public

router = APIRouter()


class ShareOptions(BaseModel):
    dates: Literal["hidden", "month", "exact"] = "hidden"
    show_origin: bool = False
    show_name: bool = False


class CreateShareBody(BaseModel):
    kind: str
    plan_id: int | None = None
    options: ShareOptions = Field(default_factory=ShareOptions)
    locale: str | None = Field(None, max_length=8)


def require_enabled() -> None:
    if not settings.sharing_v2_enabled:
        raise ApiError(404, "sharing_disabled", "Sharing is not available.")


def share_url(token: str) -> str:
    return public_url(f"/share/{token}")


def card_urls(token: str) -> dict:
    base = public_url(f"/api/share/{token}/card.png")
    return {"link": f"{base}?size=link", "story": f"{base}?size=story"}


def _public_options(share: dict) -> dict:
    return share_public.normalize_options(share.get("options"))


def _title(share: dict, plan: dict | None) -> str:
    if share["kind"] == "savings":
        return "Price alerts"
    return (plan or {}).get("name") or ""


@router.post("/shares")
def create_share(body: CreateShareBody, user: dict = Depends(get_current_user)):
    require_enabled()
    if body.kind not in share_public.KINDS:
        raise ApiError(422, "invalid_kind", "Unknown share kind.")
    plan_id = None
    if body.kind != "savings":
        plan = get_plan(body.plan_id) if body.plan_id is not None else None
        if not plan or plan["username"] != user["username"]:
            raise ApiError(404, "plan_not_found", "Plan not found.")
        plan_id = plan["id"]
    options = {**body.options.model_dump(), "locale": body.locale}
    share = shares_db.upsert_share(user["username"], body.kind, plan_id, options)
    return {
        "token": share["token"],
        "kind": share["kind"],
        "url": share_url(share["token"]),
        "card_url": card_urls(share["token"]),
        "options": _public_options(share),
        "created_at": share["created_at"],
    }


@router.get("/shares")
def list_my_shares(user: dict = Depends(get_current_user)):
    require_enabled()
    out = []
    for share in shares_db.list_shares(user["username"]):
        plan = get_plan(share["plan_id"]) if share["plan_id"] is not None else None
        out.append(
            {
                "token": share["token"],
                "kind": share["kind"],
                "title": _title(share, plan),
                "url": share_url(share["token"]),
                "options": _public_options(share),
                "created_at": share["created_at"],
            }
        )
    return {"shares": out}


@router.delete("/shares/{token}")
def revoke_my_share(token: str, user: dict = Depends(get_current_user)):
    require_enabled()
    if not shares_db.delete_share(token, user["username"]):
        raise ApiError(404, "share_not_found", "Share not found.")
    try:  # Task 2's card cache; absent until then
        from ...services import share_card

        share_card.invalidate(token)
    except (ImportError, AttributeError):
        pass
    return Response(status_code=204)


def resolve_snapshot(token: str) -> tuple[dict, dict] | None:
    """(share row, card/OG snapshot) for a live new-style share, else None."""
    if not settings.sharing_v2_enabled:
        return None
    share = shares_db.get_share(token)
    if not share:
        return None
    opts = _public_options(share)
    owner = users_db.get_user_by_username(share["username"])
    name = share_public.owner_display_name(owner, opts)
    if share["kind"] == "savings":
        summary = alert_moments.summary(owner["id"]) if owner else {}
        return share, share_public.build_snapshot(
            "savings", opts, savings=summary, owner_name=name
        )
    plan = get_plan(share["plan_id"]) if share["plan_id"] is not None else None
    if not plan or plan["username"] != share["username"]:
        return None
    return share, share_public.build_snapshot(
        share["kind"], opts, plan=plan, owner_name=name
    )


def public_payload(token: str) -> dict | None:
    """Body of the public ``GET /share/{token}`` for a new-style share."""
    found = resolve_snapshot(token)
    if not found:
        return None
    share, snap = found
    opts = _public_options(share)
    if share["kind"] == "savings":
        body = {
            "name": snap["title"],
            "created_at": share["created_at"],
            "updated_at": share["created_at"],
            "search_data": {},
            "selections": {},
        }
    else:
        plan = get_plan(share["plan_id"])
        body = share_public.sanitize_plan(plan, opts, snap["owner_name"])
    body.update(kind=share["kind"], options=opts)
    if snap["owner_name"]:
        body["owner_name"] = snap["owner_name"]
    if share["kind"] in ("recap", "savings"):
        card = {"headline": snap["headline"], "stats": snap["stats"]}
        if snap["destination"]:
            card["destination"] = snap["destination"]
        if snap["period"]:
            card["period"] = snap["period"]
        body["card"] = card
    return body
