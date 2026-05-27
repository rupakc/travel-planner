import re
from datetime import date

from pydantic import BaseModel, Field, model_validator

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
    return_date: date | None = Field(None, description="Return date for round trips")
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
    budget_usd: float | None = Field(None, description="Total trip budget in USD")
    num_travelers: int = Field(1, ge=1, le=20, description="Number of travelers")
    destinations: list[str] | None = Field(
        None,
        description="Ordered city list for multi-city trips, e.g. ['Paris', 'Rome', 'Barcelona']. "
        "destination (above) is always the primary/first city.",
    )

    # Auto-set by validator — not in the request body, not serialised to JSON
    origin_iata: str | None = Field(None, exclude=True)
    destination_iata: str | None = Field(None, exclude=True)

    @model_validator(mode="after")
    def resolve_iata_codes(self) -> "TravelSearchRequest":
        stripped_o = self.origin.strip()
        if _IATA_RE.match(stripped_o.upper()):
            self.origin_iata = stripped_o.upper()
        self.origin = _resolve_iata(self.origin)

        stripped_d = self.destination.strip()
        if _IATA_RE.match(stripped_d.upper()):
            self.destination_iata = stripped_d.upper()
        self.destination = _resolve_iata(self.destination)

        return self


class FlightFilteredSearchRequest(TravelSearchRequest):
    """Flight search with additional filters for stops, price, and times."""

    max_stops: int | None = Field(
        None, ge=0, le=2, description="Maximum stops (0=non-stop)"
    )
    max_price_usd: float | None = Field(
        None, ge=0, description="Maximum price per person in USD"
    )
    departure_time_earliest: str | None = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Earliest departure time HH:MM"
    )
    departure_time_latest: str | None = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Latest departure time HH:MM"
    )
    arrival_time_earliest: str | None = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Earliest arrival time HH:MM"
    )
    arrival_time_latest: str | None = Field(
        None, pattern=r"^\d{2}:\d{2}$", description="Latest arrival time HH:MM"
    )


class HotelFilteredSearchRequest(TravelSearchRequest):
    """Hotel search with additional room and amenity filters."""

    num_beds: int | None = Field(None, ge=1, le=4, description="Number of beds in room")
    max_price_per_night_usd: float | None = Field(
        None, ge=0, description="Maximum price per night in USD"
    )
    wifi_quality: str | None = Field(
        None, pattern=r"^(basic|good|excellent)$", description="Minimum WiFi quality"
    )
    max_distance_from_center_km: float | None = Field(
        None, ge=0, description="Maximum distance from city center in km"
    )
    private_washroom: bool | None = Field(
        None, description="Require private washroom/bathroom"
    )


class ActivityFilteredSearchRequest(TravelSearchRequest):
    """Activity search with additional filters for interests, price, dates, and rating."""

    filter_interests: list[str] = Field(
        default_factory=list, description="Interest categories to focus on"
    )
    max_price_usd: float | None = Field(
        None, ge=0, description="Maximum activity price per person in USD"
    )
    available_from: date | None = Field(None, description="Earliest availability date")
    available_to: date | None = Field(None, description="Latest availability date")
    min_rating: float | None = Field(
        None, ge=0, le=5, description="Minimum star rating (0-5)"
    )
