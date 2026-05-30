"""
Transit time estimation between two geographic coordinates.
Uses Haversine distance and city density factors.
"""

import math
from typing import Literal

CityDensity = Literal["dense", "medium", "sparse"]

DENSITY_FACTORS: dict[str, float] = {
    "dense": 0.7,
    "medium": 1.0,
    "sparse": 1.3,
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the great-circle distance in kilometres between two points."""
    R = 6371.0  # Earth radius in km
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lam = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_transit(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    city_density: CityDensity = "medium",
) -> dict:
    """
    Estimate transit time and mode between two coordinates.

    Parameters
    ----------
    lat1, lon1 : origin coordinates
    lat2, lon2 : destination coordinates
    city_density : 'dense' | 'medium' | 'sparse'
        dense  = 0.7x effective speed  (e.g. Tokyo, NYC)
        medium = 1.0x effective speed
        sparse = 1.3x effective speed  (e.g. suburban/rural)

    Returns
    -------
    dict with keys:
        minutes      : int   — estimated travel time
        mode         : str   — 'walking' | 'metro' | 'taxi' | 'car'
        description  : str   — human-readable summary
        distance_km  : float — straight-line distance
    """
    factor = DENSITY_FACTORS.get(city_density, 1.0)

    km = haversine_km(lat1, lon1, lat2, lon2)

    # Select mode and base parameters
    if km < 0.8:
        mode = "walking"
        base_speed_kmh = 5.0
        wait_min = 0
    elif km < 5.0:
        mode = "metro"
        base_speed_kmh = 20.0
        wait_min = 10
    elif km < 15.0:
        mode = "taxi"
        base_speed_kmh = 30.0
        wait_min = 5
    else:
        mode = "car"
        base_speed_kmh = 60.0
        wait_min = 0

    effective_speed = base_speed_kmh * factor
    travel_min = (km / effective_speed) * 60.0
    total_min = int(round(travel_min + wait_min))

    description = f"{total_min} min by {mode}"

    return {
        "minutes": total_min,
        "mode": mode,
        "description": description,
        "distance_km": round(km, 3),
    }
