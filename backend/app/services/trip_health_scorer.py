"""
Holistic trip health scorer.
Evaluates budget alignment, completeness, communication, pacing, and visa awareness.
"""

from typing import Any


def _grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 45:
        return "D"
    return "F"


def _status(earned: float, maximum: float) -> str:
    ratio = earned / maximum if maximum > 0 else 0.0
    if ratio >= 0.8:
        return "good"
    if ratio >= 0.5:
        return "warning"
    return "critical"


def _estimate_plan_cost(selections: dict, nights: int) -> float:
    """Best-effort cost estimate from selected items."""
    total = 0.0

    flight = selections.get("flight") or {}
    total += float(flight.get("price_usd") or 0)

    hotel = selections.get("hotel") or {}
    total += float(hotel.get("price_per_night_usd") or 0) * nights

    for activity in selections.get("activities") or []:
        total += float(activity.get("price_usd") or 0)

    sim = selections.get("sim") or {}
    total += float(sim.get("price_usd") or 0)

    return total


def compute_trip_health(selections: dict, search_data: dict) -> dict:
    """
    Compute a holistic trip health score out of 100.

    Parameters
    ----------
    selections : dict
        User's selected items — keys: 'flight', 'hotel', 'activities', 'sim', 'itinerary'.
    search_data : dict
        Original search parameters — keys: 'budget_usd', 'nights', 'num_travelers',
        'departure_date', 'return_date', etc.

    Returns
    -------
    dict with keys:
        score    : int         0-100
        grade    : str         A/B/C/D/F
        factors  : list[dict]  per-factor breakdown
        warnings : list[dict]  actionable warnings
    """
    budget_usd: float = float(search_data.get("budget_usd") or 0)
    nights: int = int(search_data.get("nights") or 7)
    num_travelers: int = int(search_data.get("num_travelers") or 1)

    flight = selections.get("flight") or {}
    hotel = selections.get("hotel") or {}
    activities: list = selections.get("activities") or []
    sim = selections.get("sim") or {}
    factors: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []

    # ── Factor 1: Budget (30 pts) ──────────────────────────────────────────
    budget_score = 0
    budget_msg = "No budget set"
    if budget_usd > 0:
        plan_cost = _estimate_plan_cost(selections, nights) * num_travelers
        ratio = plan_cost / budget_usd if budget_usd > 0 else 0
        if ratio == 0:
            budget_score = 15
            budget_msg = "No items selected yet; estimated cost unknown"
        elif ratio <= 0.80:
            budget_score = 30
            budget_msg = f"Estimated cost ${plan_cost:,.0f} is well within ${budget_usd:,.0f} budget"
        elif ratio <= 1.0:
            budget_score = 20
            budget_msg = f"Estimated cost ${plan_cost:,.0f} is close to ${budget_usd:,.0f} budget"
        elif ratio <= 1.25:
            budget_score = 10
            budget_msg = f"Estimated cost ${plan_cost:,.0f} exceeds budget by {(ratio - 1) * 100:.0f}%"
            warnings.append({"type": "budget", "message": "Plan cost exceeds budget"})
        else:
            budget_score = 0
            budget_msg = f"Estimated cost ${plan_cost:,.0f} greatly exceeds ${budget_usd:,.0f} budget"
            warnings.append(
                {
                    "type": "budget",
                    "message": "Plan cost significantly over budget — consider cheaper options",
                }
            )
    else:
        budget_score = 15
        budget_msg = "No budget constraint set"

    factors.append(
        {
            "name": "Budget",
            "score": budget_score,
            "max": 30,
            "status": _status(budget_score, 30),
            "message": budget_msg,
        }
    )

    # ── Factor 2: Completeness (25 pts) ───────────────────────────────────
    completeness_score = 0
    missing: list[str] = []

    has_flight = bool(flight and flight.get("airline"))
    has_hotel = bool(hotel and (hotel.get("name") or hotel.get("hotel_name")))
    has_activities = bool(activities)

    if has_flight:
        completeness_score += 10
    else:
        missing.append("flight")

    if has_hotel:
        completeness_score += 10
    else:
        missing.append("hotel")

    if has_activities:
        completeness_score += 5
    else:
        missing.append("activities")

    completeness_msg = (
        "All key selections made" if not missing else f"Missing: {', '.join(missing)}"
    )
    if missing:
        warnings.append(
            {
                "type": "completeness",
                "message": f"Plan is incomplete — missing {', '.join(missing)}",
            }
        )

    factors.append(
        {
            "name": "Completeness",
            "score": completeness_score,
            "max": 25,
            "status": _status(completeness_score, 25),
            "message": completeness_msg,
        }
    )

    # ── Factor 3: Communication (10 pts) ──────────────────────────────────
    has_sim = bool(
        sim and (sim.get("provider") or sim.get("name") or sim.get("plan_name"))
    )
    comm_score = 10 if has_sim else 0
    comm_msg = "SIM/eSIM plan selected" if has_sim else "No SIM/eSIM plan selected"
    if not has_sim:
        warnings.append(
            {
                "type": "communication",
                "message": "No SIM plan selected — consider local data access",
            }
        )

    factors.append(
        {
            "name": "Communication",
            "score": comm_score,
            "max": 10,
            "status": _status(comm_score, 10),
            "message": comm_msg,
        }
    )

    # ── Factor 4: Pacing (20 pts) ─────────────────────────────────────────
    pacing_score = 0
    if nights > 0 and activities:
        ratio = len(activities) / nights
        if 1.5 <= ratio <= 3.0:
            pacing_score = 20
            pacing_msg = (
                f"{len(activities)} activities over {nights} nights — well-paced"
            )
        elif 1.0 <= ratio < 1.5 or 3.0 < ratio <= 4.0:
            pacing_score = 12
            pacing_msg = f"{len(activities)} activities over {nights} nights — slightly over/under-packed"
        elif ratio < 1.0:
            pacing_score = 6
            pacing_msg = f"Only {len(activities)} activities for {nights} nights — trip may feel sparse"
            warnings.append(
                {"type": "pacing", "message": "Consider adding more activities"}
            )
        else:
            pacing_score = 6
            pacing_msg = f"{len(activities)} activities over {nights} nights — may be over-scheduled"
            warnings.append(
                {
                    "type": "pacing",
                    "message": "Trip may be over-packed; consider trimming activities",
                }
            )
    elif nights > 0:
        pacing_score = 0
        pacing_msg = "No activities selected to assess pacing"
    else:
        pacing_score = 10
        pacing_msg = "Trip duration unknown"

    factors.append(
        {
            "name": "Pacing",
            "score": pacing_score,
            "max": 20,
            "status": _status(pacing_score, 20),
            "message": pacing_msg,
        }
    )

    # ── Factor 5: Visa Awareness (15 pts) ─────────────────────────────────
    # Flat 10 pts for now; future versions can check actual visa status
    visa_score = 10
    visa_msg = "Visa requirements reviewed"

    factors.append(
        {
            "name": "Visa Awareness",
            "score": visa_score,
            "max": 15,
            "status": _status(visa_score, 15),
            "message": visa_msg,
        }
    )

    total_score = sum(f["score"] for f in factors)
    grade = _grade(total_score)

    return {
        "score": total_score,
        "grade": grade,
        "factors": factors,
        "warnings": warnings,
    }
