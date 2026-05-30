"""
Rearrange itinerary slots to move outdoor activities away from rainy/poor-weather days.
Swaps outdoor slots on poor-weather days with indoor slots on clear days.
"""

import copy

OUTDOOR_KEYWORDS: frozenset[str] = frozenset(
    {
        "hike",
        "hiking",
        "beach",
        "outdoor",
        "park",
        "garden",
        "waterfall",
        "mountain",
        "surf",
        "surfing",
        "kayak",
        "kayaking",
        "cycling",
        "cycle",
        "bike",
        "biking",
        "market",
        "street",
    }
)

INDOOR_KEYWORDS: frozenset[str] = frozenset(
    {
        "museum",
        "gallery",
        "temple",
        "shrine",
        "castle",
        "church",
        "aquarium",
        "theater",
        "theatre",
        "restaurant",
        "mall",
        "spa",
        "cooking",
        "cook",
        "class",
        "workshop",
        "cinema",
        "indoor",
    }
)


def _classify_slot(slot: dict) -> str:
    """
    Classify a slot as 'outdoor', 'indoor', or 'unknown'.
    Checks slot['activity'] and slot['location'] for keyword matches.
    """
    text = " ".join(
        [
            str(slot.get("activity") or ""),
            str(slot.get("location") or ""),
            str(slot.get("title") or ""),
            str(slot.get("description") or ""),
        ]
    ).lower()

    outdoor_hit = any(kw in text for kw in OUTDOOR_KEYWORDS)
    indoor_hit = any(kw in text for kw in INDOOR_KEYWORDS)

    if outdoor_hit and not indoor_hit:
        return "outdoor"
    if indoor_hit and not outdoor_hit:
        return "indoor"
    if outdoor_hit and indoor_hit:
        # Mixed — lean outdoor for conservative scheduling
        return "outdoor"
    return "unknown"


def _get_poor_days(weather: dict) -> set[str]:
    """Return a set of date strings where conditions are poor."""
    poor: set[str] = set()
    days: list[dict] = weather.get("days") or []
    for day in days:
        if day.get("is_poor"):
            date = day.get("date") or day.get("day")
            if date:
                poor.add(str(date))
    return poor


def _get_clear_days(weather: dict) -> set[str]:
    """Return a set of date strings where conditions are NOT poor."""
    clear: set[str] = set()
    days: list[dict] = weather.get("days") or []
    for day in days:
        if not day.get("is_poor"):
            date = day.get("date") or day.get("day")
            if date:
                clear.add(str(date))
    return clear


def adapt_itinerary_for_weather(itinerary: dict, weather: dict) -> dict:
    """
    Rearrange itinerary slots so outdoor activities fall on clear days.

    Parameters
    ----------
    itinerary : dict
        Must contain a 'days' list. Each day has a 'date' and a 'slots' list.
        Each slot has at minimum 'activity' and/or 'location' fields.
    weather : dict
        Must contain a 'days' list. Each day has 'date'/'day' and 'is_poor' (bool).

    Returns
    -------
    The itinerary dict (deep-copied and modified) with two extra fields:
        weather_adapted : bool  — True if any swaps were made
        weather_changes : list  — human-readable descriptions of each swap
    """
    if not itinerary:
        result = itinerary.copy() if isinstance(itinerary, dict) else {}
        result["weather_adapted"] = False
        result["weather_changes"] = []
        return result

    adapted = copy.deepcopy(itinerary)
    changes: list[str] = []

    poor_days = _get_poor_days(weather)
    clear_days = _get_clear_days(weather)

    if not poor_days:
        adapted["weather_adapted"] = False
        adapted["weather_changes"] = []
        return adapted

    days: list[dict] = adapted.get("days") or []

    # Build index: date -> day_index -> list of (slot_index, slot)
    date_to_idx: dict[str, int] = {}
    for i, day in enumerate(days):
        date = str(day.get("date") or day.get("day") or "")
        if date:
            date_to_idx[date] = i

    # Collect outdoor slots on poor days and indoor slots on clear days
    OutdoorCandidate = dict  # {date, day_idx, slot_idx, slot}
    IndoorCandidate = dict

    outdoor_on_poor: list[OutdoorCandidate] = []
    indoor_on_clear: list[IndoorCandidate] = []

    for date, day_idx in date_to_idx.items():
        slots: list[dict] = days[day_idx].get("slots") or []
        for slot_idx, slot in enumerate(slots):
            kind = _classify_slot(slot)
            if date in poor_days and kind == "outdoor":
                outdoor_on_poor.append(
                    {
                        "date": date,
                        "day_idx": day_idx,
                        "slot_idx": slot_idx,
                        "slot": slot,
                    }
                )
            elif date in clear_days and kind == "indoor":
                indoor_on_clear.append(
                    {
                        "date": date,
                        "day_idx": day_idx,
                        "slot_idx": slot_idx,
                        "slot": slot,
                    }
                )

    if not outdoor_on_poor:
        adapted["weather_adapted"] = False
        adapted["weather_changes"] = []
        return adapted

    # Perform swaps greedily
    used_indoor: set[tuple[int, int]] = set()

    for outdoor_cand in outdoor_on_poor:
        # Find the first unused indoor candidate on a different (clear) day
        swap_target: IndoorCandidate | None = None
        for indoor_cand in indoor_on_clear:
            key = (indoor_cand["day_idx"], indoor_cand["slot_idx"])
            if key not in used_indoor and indoor_cand["date"] != outdoor_cand["date"]:
                swap_target = indoor_cand
                break

        if swap_target is None:
            continue

        # Perform the swap in the deep-copied structure
        o_day_idx = outdoor_cand["day_idx"]
        o_slot_idx = outdoor_cand["slot_idx"]
        i_day_idx = swap_target["day_idx"]
        i_slot_idx = swap_target["slot_idx"]

        outdoor_slot = days[o_day_idx]["slots"][o_slot_idx]
        indoor_slot = days[i_day_idx]["slots"][i_slot_idx]

        days[o_day_idx]["slots"][o_slot_idx] = indoor_slot
        days[i_day_idx]["slots"][i_slot_idx] = outdoor_slot

        used_indoor.add((i_day_idx, i_slot_idx))

        outdoor_name = (
            outdoor_cand["slot"].get("activity")
            or outdoor_cand["slot"].get("title")
            or "Outdoor activity"
        )
        indoor_name = (
            swap_target["slot"].get("activity")
            or swap_target["slot"].get("title")
            or "Indoor activity"
        )

        changes.append(
            f"Moved '{outdoor_name}' from {outdoor_cand['date']} (poor weather) "
            f"to {swap_target['date']}; swapped with '{indoor_name}'"
        )

    adapted["weather_adapted"] = len(changes) > 0
    adapted["weather_changes"] = changes
    return adapted
