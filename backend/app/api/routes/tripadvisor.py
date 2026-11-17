"""Tripadvisor ratings, live and on demand (docs/Tripadvisor.md).

``POST /api/tripadvisor/attractions`` — signed-in users only, its own
``tripadvisor`` rate bucket, 404 unless TRIPADVISOR_ENABLED and a key are
set. The answer is never cached (``Cache-Control: no-store``) and never
indexable (``X-Robots-Tag``); clients keep it in memory only.

``GET /api/admin/tripadvisor/budget`` — admin: billable entities used / cap.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints

from ...core.auth import get_current_user, require_admin
from ...core.errors import ApiError
from ...core.rate_limit import rate_limit
from ...db.places_db import resolve_place
from ...services import tripadvisor

router = APIRouter()

NO_STORE = {
    "Cache-Control": "no-store",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


class AttractionsRequest(BaseModel):
    destination: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


def _enabled() -> None:
    if not tripadvisor.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


@router.post(
    "/tripadvisor/attractions",
    dependencies=[
        Depends(_enabled),
        Depends(get_current_user),
        Depends(rate_limit("tripadvisor")),
    ],
)
async def tripadvisor_attractions(body: AttractionsRequest, response: Response):
    response.headers.update(NO_STORE)
    place = resolve_place(body.destination)
    if place is None or place.lat is None or place.lng is None:
        raise ApiError(
            422,
            "unknown_destination",
            "We couldn't place that destination on the map.",
            headers=NO_STORE,
        )
    try:
        return await tripadvisor.attractions(place)
    except tripadvisor.TerraError as exc:
        raise ApiError(
            502,
            "tripadvisor_unavailable",
            "Tripadvisor ratings are unavailable right now. Try again later.",
            headers=NO_STORE,
        ) from exc


@router.get("/admin/tripadvisor/budget")
def admin_tripadvisor_budget(_admin: dict = Depends(require_admin)):
    return tripadvisor.budget_status()
