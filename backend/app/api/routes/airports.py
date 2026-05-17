from fastapi import APIRouter, Query
from ...db.database import search_airports

router = APIRouter()


@router.get("/airports/search")
async def airport_search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search airports by IATA code, city, name, or country."""
    results = search_airports(q, limit=limit)
    return results
