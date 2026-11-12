"""Share links 2.0 (Phase 4): create, list and revoke; public payloads.

``POST/GET/DELETE /api/shares`` need sign-in and the ``share_manage`` bucket
(router dependency in main.py). Every route answers 404 ``sharing_disabled``
while ``SHARING_V2_ENABLED`` is off.
"""

import html
from typing import Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field

from ...core.auth import get_current_user
from ...core.config import settings
from ...core.errors import ApiError
from ...core.urls import request_public_url
from ...db import shares_db, users_db
from ...db.plans_db import get_plan, get_user_plans
from ...services import alert_moments, share_card, share_public

router = APIRouter()
# Public crawler/preview routes: own bucket (wired in main.py), no sign-in.
public_router = APIRouter()


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


def share_url(token: str, request: Request | None = None) -> str:
    return request_public_url(f"/share/{token}", request)


def card_urls(token: str, request: Request | None = None) -> dict:
    base = request_public_url(f"/api/share/{token}/card.png", request)
    return {"link": f"{base}?size=link", "story": f"{base}?size=story"}


def _public_options(share: dict) -> dict:
    return share_public.normalize_options(share.get("options"))


def _title(share: dict, plan: dict | None) -> str:
    if share["kind"] == "savings":
        return "Price alerts"
    return (plan or {}).get("name") or ""


@router.post("/shares")
def create_share(
    body: CreateShareBody, request: Request, user: dict = Depends(get_current_user)
):
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
        "plan_id": share.get("plan_id"),
        "url": share_url(share["token"], request),
        "card_url": card_urls(share["token"], request),
        "options": _public_options(share),
        "created_at": share["created_at"],
    }


@router.get("/shares")
def list_my_shares(request: Request, user: dict = Depends(get_current_user)):
    require_enabled()
    out = []
    for share in shares_db.list_shares(user["username"]):
        plan = get_plan(share["plan_id"]) if share["plan_id"] is not None else None
        out.append(
            {
                "token": share["token"],
                "kind": share["kind"],
                "plan_id": share.get("plan_id"),
                "title": _title(share, plan),
                "url": share_url(share["token"], request),
                "options": _public_options(share),
                "created_at": share["created_at"],
            }
        )
    # Plans still shared through the legacy token (POST /plans/{id}/share):
    # the only place the token is exposed, as part of its public URL.
    legacy = [
        {
            "plan_id": p["id"],
            "name": p.get("name"),
            "url": share_url(p["share_token"], request),
        }
        for p in get_user_plans(user["username"])
        if p.get("share_token")
    ]
    return {"shares": out, "legacy_plan_shares": legacy}


@router.delete("/shares/{token}")
def revoke_my_share(token: str, user: dict = Depends(get_current_user)):
    require_enabled()
    if not shares_db.delete_share(token, user["username"]):
        raise ApiError(404, "share_not_found", "Share not found.")
    share_card.invalidate(token)
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
        stamp = share_public._stamp(share["created_at"], opts["dates"])
        body = {
            "name": snap["title"],
            "created_at": stamp,
            "updated_at": stamp,
            "search_data": {},
            "selections": {},
        }
    else:
        plan = get_plan(share["plan_id"])
        body = share_public.sanitize_plan(plan, opts, snap["owner_name"])
        if share["kind"] == "recap":  # a recap shows only its card
            body["search_data"] = {}
            body["selections"] = {}
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


_NOINDEX = {"X-Robots-Tag": "noindex, nofollow"}


def _description(snap: dict) -> str:
    parts = [share_card.stat_text(s) for s in snap["stats"]]
    month = share_card.month_label(snap["period"])
    if month:
        parts.insert(0, month)
    if snap["owner_name"]:
        parts.append(f"by {snap['owner_name']}")
    return " · ".join(parts) or "Planned with Voyager"


def _page_html(token: str, snap: dict, request: Request, lang: str) -> str:
    e = lambda v: html.escape(str(v), quote=True)  # noqa: E731
    title = snap["headline"] or "My trip"
    url = share_url(token, request)
    image = card_urls(token, request)["link"]
    desc = _description(snap)
    return f"""<!doctype html>
<html lang="{e(lang)}">
<head>
<meta charset="utf-8">
<title>{e(title)}</title>
<meta name="robots" content="noindex, nofollow">
<meta name="description" content="{e(desc)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Voyager">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{e(url)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)}">
<meta name="twitter:description" content="{e(desc)}">
<meta name="twitter:image" content="{e(image)}">
</head>
<body>
<h1>{e(title)}</h1>
<p>{e(desc)}</p>
<p><a href="{e(url)}">Open on Voyager</a></p>
</body>
</html>
"""


@public_router.get("/share/{token}/page")
def share_page(token: str, request: Request):
    found = resolve_snapshot(token)
    if not found:
        raise ApiError(404, "share_not_found", "Share not found.")
    share, snap = found
    lang = (share["options"].get("locale") or "en") if share.get("options") else "en"
    if lang not in ("en", "es", "de", "fr", "hi", "zh", "bn"):
        lang = "en"
    body = _page_html(token, snap, request, lang)
    return Response(
        body,
        media_type="text/html",
        headers={**_NOINDEX, "Cache-Control": "public, max-age=300"},
    )


@public_router.get("/share/{token}/card.png")
def share_card_png(token: str, size: Literal["link", "story"] = "link"):
    found = resolve_snapshot(token)
    if not found:
        raise ApiError(404, "share_not_found", "Share not found.")
    try:
        png = share_card.get_card(token, found[1], size)
    except share_card.RenderBusy:
        raise ApiError(503, "card_busy", "Card rendering is busy; retry shortly.")
    return Response(
        png,
        media_type="image/png",
        headers={**_NOINDEX, "Cache-Control": "public, max-age=300"},
    )
