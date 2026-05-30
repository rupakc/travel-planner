"""
Score hotels by their proximity to a list of activities.
Depends on transit_estimator for Haversine distance and mode estimation.
"""

from typing import Any

from .transit_estimator import estimate_transit

# Threshold constants (minutes)
HIGH_WEIGHT_THRESHOLD = 20
LOW_WEIGHT_THRESHOLD = 40

# Scoring weights per activity slot
HIGH_WEIGHT = 2
LOW_WEIGHT = 1


def _extract_coords(obj: dict) -> tuple[float, float] | None:
    """Try common field name variants for lat/lng."""
    lat = obj.get("lat") or obj.get("latitude")
    lng = obj.get("lng") or obj.get("lon") or obj.get("longitude")
    if lat is None or lng is None:
        return None
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None


def score_hotel_location(hotel: dict, activities: list[dict]) -> dict:
    """
    Score a hotel's location based on how quickly guests can reach activities.

    Parameters
    ----------
    hotel : dict
        Must contain lat/lng coordinates (tries 'lat','lng','latitude','longitude').
    activities : list of dict
        Each activity should contain lat/lng and 'name'. Activities missing
        coordinates are silently skipped.

    Returns
    -------
    dict with keys:
        proximity_score    : int   0-100
        nearby_count       : int   number of activities reachable within 40 min
        avg_minutes        : float | None  average transit time to reachable activities
        nearest_activities : list  top-5 nearest activities with name/minutes/mode
    """
    hotel_coords = _extract_coords(hotel)
    if hotel_coords is None:
        return {
            "proximity_score": 0,
            "nearby_count": 0,
            "avg_minutes": None,
            "nearest_activities": [],
        }

    h_lat, h_lng = hotel_coords

    transit_results: list[dict[str, Any]] = []
    for activity in activities:
        a_coords = _extract_coords(activity)
        if a_coords is None:
            continue
        a_lat, a_lng = a_coords
        transit = estimate_transit(h_lat, h_lng, a_lat, a_lng)
        transit_results.append(
            {
                "name": activity.get("name", "Activity"),
                "minutes": transit["minutes"],
                "mode": transit["mode"],
                "distance_km": transit["distance_km"],
            }
        )

    if not transit_results:
        return {
            "proximity_score": 0,
            "nearby_count": 0,
            "avg_minutes": None,
            "nearest_activities": [],
        }

    # Sort by transit time ascending
    transit_results.sort(key=lambda x: x["minutes"])

    # Compute weighted score
    high_count = sum(
        1 for r in transit_results if r["minutes"] <= HIGH_WEIGHT_THRESHOLD
    )
    low_count = sum(
        1
        for r in transit_results
        if HIGH_WEIGHT_THRESHOLD < r["minutes"] <= LOW_WEIGHT_THRESHOLD
    )
    nearby_count = high_count + low_count

    total_possible = len(transit_results) * HIGH_WEIGHT
    earned = high_count * HIGH_WEIGHT + low_count * LOW_WEIGHT
    proximity_score = (
        int(round((earned / total_possible) * 100)) if total_possible > 0 else 0
    )
    proximity_score = max(0, min(100, proximity_score))

    reachable = [r for r in transit_results if r["minutes"] <= LOW_WEIGHT_THRESHOLD]
    avg_minutes: float | None = (
        round(sum(r["minutes"] for r in reachable) / len(reachable), 1)
        if reachable
        else None
    )

    nearest_activities = [
        {"name": r["name"], "minutes": r["minutes"], "mode": r["mode"]}
        for r in transit_results[:5]
    ]

    return {
        "proximity_score": proximity_score,
        "nearby_count": nearby_count,
        "avg_minutes": avg_minutes,
        "nearest_activities": nearest_activities,
    }
