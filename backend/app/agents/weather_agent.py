from datetime import date, timedelta

import httpx

from ..schemas.request import TravelSearchRequest
from ..utils.geo import CITY_COORDS
from .base_agent import BaseAgent
from .loader import load_agent_definition

_METEO_URL = "https://api.open-meteo.com/v1/forecast"

_WMO_LABELS: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Icy fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Rain showers",
    81: "Heavy showers",
    82: "Violent showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm + hail",
    99: "Thunderstorm + heavy hail",
}


class WeatherAgent(BaseAgent):
    def __init__(self, agents_dir: str):
        super().__init__(load_agent_definition(agents_dir, "weather"))

    async def run(self, request: TravelSearchRequest) -> dict:
        dep = request.departure_date
        ret = request.return_date or (dep + timedelta(days=7))
        days_out = (dep - date.today()).days

        if request.is_multi_city:
            return await self._run_multi_city(request, days_out)

        # Strip country suffix — "Tokyo, Japan" → "tokyo"
        city_key = request.destination.lower().strip().split(",")[0].strip()
        coords = CITY_COORDS.get(city_key)

        if days_out <= 16 and coords:
            result = await self._fetch_open_meteo(coords, dep, ret)
            if "error" not in result:
                return result

        return await self._llm_estimate(request, dep, ret)

    async def _run_multi_city(
        self, request: TravelSearchRequest, days_out: int
    ) -> dict:
        """Forecast every city for the dates the traveler is actually there."""
        stays = request.city_stays or []
        all_days: list[dict] = []
        missing: list[dict] = []

        for stay in stays:
            city_key = stay["city"].lower().strip().split(",")[0].strip()
            coords = CITY_COORDS.get(city_key)
            result: dict = {"error": "no coords"}
            if days_out <= 16 and coords:
                result = await self._fetch_open_meteo(
                    coords, stay["start_date"], stay["end_date"]
                )
            if "error" in result:
                missing.append(stay)
                continue
            for day in result.get("days", []):
                day["city"] = stay["city"]
            all_days.extend(result.get("days", []))

        if missing:
            llm = await self._llm_estimate_cities(request, missing)
            all_days.extend(llm)

        if not all_days:
            return await self._llm_estimate(
                request,
                request.departure_date,
                request.return_date or request.departure_date + timedelta(days=7),
            )

        # Journey order first, then chronology — the strip of day cards must
        # follow the user's stop order even at shared boundary dates.
        stay_order = {
            s["city"].lower().split(",")[0].strip(): i for i, s in enumerate(stays)
        }
        all_days.sort(
            key=lambda d: (
                stay_order.get(
                    (d.get("city") or "").lower().split(",")[0].strip(), len(stays)
                ),
                d.get("date") or "",
            )
        )
        # LLM ranges are end-inclusive, so the hand-over date can appear twice
        # for the same city — keep the first occurrence only. A genuine
        # boundary day (in city A morning, city B evening) has distinct cities
        # and survives.
        seen: set[tuple] = set()
        all_days = [
            d
            for d in all_days
            if (key := (str(d.get("date")), (d.get("city") or "").lower())) not in seen
            and not seen.add(key)
        ]
        poor_count = sum(1 for d in all_days if d.get("is_poor"))
        return {
            "days": all_days,
            "poor_weather_day_count": poor_count,
            "cities": [s["city"] for s in stays],
            "source": "open-meteo" if not missing else "open-meteo+llm-estimate",
        }

    async def _llm_estimate_cities(
        self, request: TravelSearchRequest, stays: list[dict]
    ) -> list[dict]:
        """One LLM call covering the cities open-meteo couldn't serve."""
        ranges = "\n".join(
            f"- {s['city']}: {s['start_date']} to {s['end_date']}" for s in stays
        )
        prompt = (
            "Produce day-by-day climate estimates for each city and date range "
            f"below (historical seasonal averages, specific per day):\n{ranges}\n"
            'Every day object MUST include a "city" field naming its city.'
        )
        result = await self.execute(prompt)
        if "error" in result:
            return []
        days = self._flatten_days(result, stays)
        # Deterministic city assignment from the stay date ranges — dates are
        # authoritative; the LLM sometimes omits, blanks, or mislabels cities
        for day in days:
            d = str(day.get("date") or "")
            for stay in stays:
                if str(stay["start_date"]) <= d < str(stay["end_date"]):
                    day["city"] = stay["city"]
                    break
            else:
                if stays and d == str(stays[-1]["end_date"]):
                    day["city"] = stays[-1]["city"]
        return days

    @staticmethod
    def _flatten_days(result: dict, stays: list[dict]) -> list[dict]:
        """Extract a flat day list even when the LLM nests days per city.

        Despite the flat-array instruction, the model sometimes returns
        {"paris": {"days": [...]}, "rome": {"days": [...]}} — losing every
        day. Accept the flat shape first, then salvage nested ones in the
        journey (stay) order.
        """
        days = result.get("days")
        if isinstance(days, list) and days:
            return [d for d in days if isinstance(d, dict)]

        nested: list[tuple[str, list[dict]]] = []
        for key, value in result.items():
            if isinstance(value, dict) and isinstance(value.get("days"), list):
                nested.append((key, [d for d in value["days"] if isinstance(d, dict)]))
            elif (
                isinstance(value, list)
                and value
                and all(isinstance(d, dict) and d.get("date") for d in value)
            ):
                nested.append((key, value))
        if not nested:
            return []

        order = {
            s["city"].lower().split(",")[0].strip(): i for i, s in enumerate(stays)
        }
        nested.sort(key=lambda kv: order.get(kv[0].lower().split(",")[0].strip(), 99))
        flat: list[dict] = []
        for key, city_days in nested:
            for day in city_days:
                day.setdefault("city", key.title())
                flat.append(day)
        return flat

    async def _fetch_open_meteo(self, coords: tuple, dep: date, ret: date) -> dict:
        params = {
            "latitude": coords[0],
            "longitude": coords[1],
            "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum,windspeed_10m_max",
            "start_date": str(dep),
            "end_date": str(ret),
            "timezone": "auto",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(_METEO_URL, params=params)
                r.raise_for_status()
                raw = r.json()
        except Exception as e:
            return {"error": str(e)}

        daily = raw.get("daily", {})
        dates = daily.get("time", [])
        days = []
        for i, d in enumerate(dates):
            code = int(daily["weathercode"][i] or 0)
            precip = float(daily["precipitation_sum"][i] or 0)
            days.append(
                {
                    "date": d,
                    "description": _WMO_LABELS.get(code, "Unknown"),
                    "weather_code": code,
                    "temp_high_c": daily["temperature_2m_max"][i],
                    "temp_low_c": daily["temperature_2m_min"][i],
                    "precipitation_mm": precip,
                    "wind_kmh": daily["windspeed_10m_max"][i],
                    "is_poor": code >= 61 or precip > 5,
                }
            )
        poor_count = sum(1 for d in days if d["is_poor"])
        return {
            "days": days,
            "poor_weather_day_count": poor_count,
            "source": "open-meteo",
        }

    async def _llm_estimate(
        self, request: TravelSearchRequest, dep: date, ret: date
    ) -> dict:
        prompt = (
            f"Destination: {request.destination}\n"
            f"Travel dates: {dep} to {ret}\n"
            "Produce day-by-day climate estimates for the trip period. "
            "Use historical seasonal averages. Be specific per day."
        )
        result = await self.execute(prompt)
        if "error" not in result:
            result.setdefault("source", "llm-estimate")
        return result
