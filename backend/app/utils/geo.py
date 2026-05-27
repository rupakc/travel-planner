import math

CITY_COORDS: dict[str, tuple[float, float]] = {
    "amsterdam": (52.3676, 4.9041),
    "athens": (37.9838, 23.7275),
    "bangkok": (13.7563, 100.5018),
    "barcelona": (41.3851, 2.1734),
    "beijing": (39.9042, 116.4074),
    "berlin": (52.5200, 13.4050),
    "brussels": (50.8503, 4.3517),
    "budapest": (47.4979, 19.0402),
    "cairo": (30.0444, 31.2357),
    "cape town": (-33.9249, 18.4241),
    "chicago": (41.8781, -87.6298),
    "copenhagen": (55.6761, 12.5683),
    "dubai": (25.2048, 55.2708),
    "dublin": (53.3498, -6.2603),
    "edinburgh": (55.9533, -3.1883),
    "florence": (43.7696, 11.2558),
    "frankfurt": (50.1109, 8.6821),
    "hong kong": (22.3193, 114.1694),
    "istanbul": (41.0082, 28.9784),
    "kuala lumpur": (3.1390, 101.6869),
    "kyoto": (35.0116, 135.7681),
    "lisbon": (38.7169, -9.1395),
    "london": (51.5074, -0.1278),
    "los angeles": (34.0522, -118.2437),
    "madrid": (40.4168, -3.7038),
    "marrakech": (31.6295, -7.9811),
    "melbourne": (-37.8136, 144.9631),
    "mexico city": (19.4326, -99.1332),
    "miami": (25.7617, -80.1918),
    "milan": (45.4654, 9.1859),
    "montreal": (45.5017, -73.5673),
    "moscow": (55.7558, 37.6173),
    "mumbai": (19.0760, 72.8777),
    "munich": (48.1351, 11.5820),
    "nairobi": (-1.2921, 36.8219),
    "new delhi": (28.6139, 77.2090),
    "new york": (40.7128, -74.0060),
    "nice": (43.7102, 7.2620),
    "oslo": (59.9139, 10.7522),
    "osaka": (34.6937, 135.5023),
    "paris": (48.8566, 2.3522),
    "prague": (50.0755, 14.4378),
    "reykjavik": (64.1265, -21.8174),
    "rio de janeiro": (-22.9068, -43.1729),
    "rome": (41.9028, 12.4964),
    "san francisco": (37.7749, -122.4194),
    "seoul": (37.5665, 126.9780),
    "shanghai": (31.2304, 121.4737),
    "singapore": (1.3521, 103.8198),
    "stockholm": (59.3293, 18.0686),
    "sydney": (-33.8688, 151.2093),
    "taipei": (25.0330, 121.5654),
    "tel aviv": (32.0853, 34.7818),
    "tokyo": (35.6762, 139.6503),
    "toronto": (43.6532, -79.3832),
    "vancouver": (49.2827, -123.1207),
    "venice": (45.4408, 12.3155),
    "vienna": (48.2082, 16.3738),
    "warsaw": (52.2297, 21.0122),
    "zurich": (47.3769, 8.5417),
}


def lookup_coords(name: str) -> tuple[float, float] | None:
    """Fast lookup from the static CITY_COORDS dict."""
    return CITY_COORDS.get(name.lower().strip()) if name else None


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    dl = math.radians(lat2 - lat1)
    dg = math.radians(lng2 - lng1)
    a = (
        math.sin(dl / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dg / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def optimize_city_order(cities: list[str], lock_first: bool = True) -> list[str]:
    """
    Nearest-neighbor TSP. lock_first=True keeps the first city as the fixed start.
    Falls back to original order if any city is not in CITY_COORDS.
    """
    normed = [c.lower().strip() for c in cities]
    coords = [CITY_COORDS.get(n) for n in normed]
    if any(c is None for c in coords):
        return cities

    start = 0
    visited = [False] * len(cities)
    visited[start] = True
    order = [start]

    for _ in range(len(cities) - 1):
        cur = order[-1]
        best, best_d = -1, float("inf")
        for j in range(len(cities)):
            if not visited[j]:
                d = haversine_km(*coords[cur], *coords[j])
                if d < best_d:
                    best_d, best = d, j
        visited[best] = True
        order.append(best)

    return [cities[i] for i in order]
