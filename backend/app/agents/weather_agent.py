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

        # Strip country suffix — "Tokyo, Japan" → "tokyo"
        city_key = request.destination.lower().strip().split(",")[0].strip()
        coords = CITY_COORDS.get(city_key)

        if days_out <= 16 and coords:
            result = await self._fetch_open_meteo(coords, dep, ret)
            if "error" not in result:
                return result

        return await self._llm_estimate(request, dep, ret)

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
