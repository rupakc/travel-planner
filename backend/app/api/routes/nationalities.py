from fastapi import APIRouter, Query
from ...db.database import search_nationalities

router = APIRouter()


@router.get("/nationalities/search")
async def nationality_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search nationalities by nationality name or country name."""
    results = search_nationalities(q, limit=limit)
    return results
