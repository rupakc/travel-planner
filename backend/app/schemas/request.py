import re
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from datetime import date

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _resolve_iata(value: str) -> str:
    """If value looks like a bare IATA code, resolve it to 'City, Country'."""
    stripped = value.strip()
    if _IATA_RE.match(stripped.upper()):
        from ..db.database import lookup_iata

        info = lookup_iata(stripped)
        if info:
            return f"{info['city']}, {info['country']}"
    return value


class TravelSearchRequest(BaseModel):
    origin: str = Field(..., description="Origin airport or city code (e.g. NYC, LHR)")
    destination: str = Field(
        ..., description="Destination airport or city (e.g. Tokyo, Paris)"
    )
    departure_date: date = Field(..., description="Departure date")
    return_date: Optional[date] = Field(None, description="Return date for round trips")
    interests: list[str] = Field(
        default_factory=list,
        description="Traveler interests e.g. food, history, adventure",
    )
    nationality: str = Field(
        ..., description="Traveler's nationality/citizenship (e.g. American, Indian)"
    )
    residence_permits: list[str] = Field(
        default_factory=list,
        description="Any residence permits held (e.g. Schengen, UK, UAE)",
    )
    existing_visas: list[str] = Field(
        default_factory=list,
        description="Any existing visas held (e.g. US, Japan, Canada)",
    )
    budget_usd: Optional[float] = Field(None, description="Total trip budget in USD")
    num_travelers: int = Field(1, ge=1, le=20, description="Number of travelers")

    @model_validator(mode="after")
    def resolve_iata_codes(self) -> "TravelSearchRequest":
        self.origin = _resolve_iata(self.origin)
        self.destination = _resolve_iata(self.destination)
        return self


class FlightFilteredSearchRequest(TravelSearchRequest):
    """Flight search with additional filters for stops, price, and times."""

    max_stops: Optional[int] = Field(
        None, ge=0, le=2, description="Maximum stops (0=non-stop)"
    )
    max_price_usd: Optional[float] = Field(
        None, ge=0, description="Maximum price per person in USD"
    )
    departure_time_earliest: Optional[str] = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Earliest departure time HH:MM"
    )
    departure_time_latest: Optional[str] = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Latest departure time HH:MM"
    )
    arrival_time_earliest: Optional[str] = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Earliest arrival time HH:MM"
    )
    arrival_time_latest: Optional[str] = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Latest arrival time HH:MM"
    )


class HotelFilteredSearchRequest(TravelSearchRequest):
    """Hotel search with additional room and amenity filters."""

    num_beds: Optional[int] = Field(
        None, ge=1, le=4, description="Number of beds in room"
    )
    max_price_per_night_usd: Optional[float] = Field(
        None, ge=0, description="Maximum price per night in USD"
    )
    wifi_quality: Optional[str] = Field(
        None, pattern=r"^(basic|good|excellent)$", description="Minimum WiFi quality"
    )
    max_distance_from_center_km: Optional[float] = Field(
        None, ge=0, description="Maximum distance from city center in km"
    )
    private_washroom: Optional[bool] = Field(
        None, description="Require private washroom/bathroom"
    )


class ActivityFilteredSearchRequest(TravelSearchRequest):
    """Activity search with additional filters for interests, price, dates, and rating."""

    filter_interests: list[str] = Field(
        default_factory=list, description="Interest categories to focus on"
    )
    max_price_usd: Optional[float] = Field(
        None, ge=0, description="Maximum activity price per person in USD"
    )
    available_from: Optional[date] = Field(
        None, description="Earliest availability date"
    )
    available_to: Optional[date] = Field(None, description="Latest availability date")
    min_rating: Optional[float] = Field(
        None, ge=0, le=5, description="Minimum star rating (0-5)"
    )
