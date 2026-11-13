"""Open-Meteo forecast client (free, no key, non-commercial; CC BY 4.0).

Weather data by Open-Meteo.com (https://open-meteo.com). The free tier allows
under 10,000 calls a day, 5,000 an hour and 600 a minute, so every call goes
through an in-memory TTL cache keyed by the rounded coordinates, and
``weather_push`` adds an hourly call budget on top."""

import logging
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

ATTRIBUTION = "Weather data by Open-Meteo.com"
URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 6.0
CACHE_TTL_S = 3 * 3600


@dataclass
class Forecast:
    """Hourly values keyed by the destination-local ``YYYY-MM-DDTHH:00``."""

    utc_offset_s: int = 0
    precip_prob: dict[str, float] = field(default_factory=dict)  # percent
    precip_mm: dict[str, float] = field(default_factory=dict)
    apparent_c: dict[str, float] = field(default_factory=dict)


class WeatherClient(Protocol):
    def forecast(self, lat: float, lng: float) -> Forecast | None: ...


def parse(payload: dict) -> Forecast | None:
    h = payload.get("hourly") if isinstance(payload, dict) else None
    if not isinstance(h, dict) or not isinstance(h.get("time"), list):
        return None
    fc = Forecast(utc_offset_s=int(payload.get("utc_offset_seconds") or 0))
    for name, target in (
        ("precipitation_probability", fc.precip_prob),
        ("precipitation", fc.precip_mm),
        ("apparent_temperature", fc.apparent_c),
    ):
        vals = h.get(name)
        if not isinstance(vals, list):
            continue
        for t, v in zip(h["time"], vals):
            if isinstance(t, str) and isinstance(v, (int, float)):
                target[t] = float(v)
    return fc


class OpenMeteoClient:
    def __init__(self, http: httpx.Client | None = None, ttl_s: int = CACHE_TTL_S):
        self._http = http
        self._ttl = ttl_s
        self._cache: dict[tuple, tuple[float, Forecast | None]] = {}
        self.calls = 0

    def forecast(self, lat: float, lng: float) -> Forecast | None:
        key = (round(lat, 1), round(lng, 1), time.strftime("%Y-%m-%d", time.gmtime()))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < self._ttl:
            return hit[1]
        self.calls += 1
        fc = None
        try:
            params = {
                "latitude": f"{key[0]:.1f}",
                "longitude": f"{key[1]:.1f}",
                "hourly": "precipitation_probability,precipitation,apparent_temperature",
                "forecast_days": 3,
                "timezone": "auto",
            }
            if self._http is not None:
                r = self._http.get(URL, params=params, timeout=TIMEOUT_S)
            else:
                r = httpx.get(URL, params=params, timeout=TIMEOUT_S)
            r.raise_for_status()
            fc = parse(r.json())
        except Exception:  # noqa: BLE001
            logger.warning("weather forecast failed", exc_info=True)
        if len(self._cache) > 500:
            self._cache.clear()
        self._cache[key] = (time.monotonic(), fc)
        return fc
