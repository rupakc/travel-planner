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
    adults: int = Field(default=1, ge=0, description="Number of adults (18-64)")
    children: int = Field(default=0, ge=0, description="Number of children (5-17)")
    seniors: int = Field(default=0, ge=0, description="Number of seniors (65+)")
    infants: int = Field(default=0, ge=0, description="Number of infants (0-4)")
    accessibility_needs: list[str] = Field(
        default_factory=list,
        description="Accessibility requirements e.g. wheelchair, visual_impairment, hearing_impairment, cognitive_disability",
    )
    destinations: list[str] | None = Field(
        None,
        description="Ordered city list for multi-city trips, e.g. ['Paris', 'Rome', 'Barcelona']. "
        "destination (above) is always the primary/first city.",
    )
    pace: str = Field(
        "balanced",
        pattern=r"^(relaxed|balanced|packed)$",
        description="Trip pacing: relaxed (fewer activities, downtime), balanced, "
        "or packed (maximise sightseeing)",
    )
    serendipity: float = Field(
        0.5,
        ge=0.0,
        le=1.0,
        description="0 = famous classics only, 0.5 = balanced mix, "
        "1 = hidden gems and local favourites",
    )

    # Server-set from the authenticated user's Taste Graph (never client input).
    # Included in serialisation so cached search results are per-profile.
    taste_context: str | None = Field(
        None,
        description="Learned taste profile summary injected into agent prompts. "
        "Overwritten server-side; client-supplied values are ignored.",
    )

    # Auto-set by validator — not in the request body, not serialised to JSON
    origin_iata: str | None = Field(None, exclude=True)
    destination_iata: str | None = Field(None, exclude=True)

    @property
    def serendipity_context(self) -> str | None:
        """Prompt snippet mapping the serendipity dial to result style, or None."""
        if self.serendipity < 0.33:
            return (
                "SERENDIPITY DIAL — CLASSICS: The traveler wants the famous, "
                "iconic, can't-miss options. Prioritise world-renowned "
                "attractions and top-rated mainstream picks. Set "
                '"hidden_gem": false on every result.'
            )
        if self.serendipity > 0.66:
            return (
                "SERENDIPITY DIAL — HIDDEN GEMS: The traveler wants to go off "
                "the beaten path. Prioritise lesser-known local favourites, "
                "neighbourhood spots, and under-the-radar experiences over "
                "famous attractions (include at most 2-3 iconic must-sees). "
                'Mark each off-the-beaten-path result with "hidden_gem": true '
                "and famous ones with false."
            )
        return (
            "SERENDIPITY DIAL — BALANCED: Mix famous must-see attractions "
            "with a few lesser-known local favourites. Mark the "
            'off-the-beaten-path results with "hidden_gem": true.'
        )

    @property
    def is_multi_city(self) -> bool:
        return bool(self.destinations and len(self.destinations) > 1)

    @property
    def destination_label(self) -> str:
        """'Paris → Rome → Barcelona' for multi-city, else the destination."""
        if self.is_multi_city:
            return " → ".join(self.destinations)
        return self.destination

    @property
    def multi_city_context(self) -> str | None:
        """Prompt snippet describing the multi-city scope, or None."""
        if not self.is_multi_city:
            return None
        return (
            f"This is a MULTI-CITY trip covering, in order: "
            f"{', '.join(self.destinations)}. "
            "Cover ALL of these cities in the results and add a 'city' field "
            "to every result so it can be grouped by city."
        )

    @property
    def traveler_context(self) -> str:
        parts = []
        if self.adults:
            parts.append(f"{self.adults} adult{'s' if self.adults != 1 else ''}")
        if self.children:
            parts.append(
                f"{self.children} child{'ren' if self.children != 1 else ''} (5-17)"
            )
        if self.seniors:
            parts.append(
                f"{self.seniors} senior{'s' if self.seniors != 1 else ''} (65+)"
            )
        if self.infants:
            parts.append(
                f"{self.infants} infant{'s' if self.infants != 1 else ''} (0-4)"
            )
        base = ", ".join(parts) if parts else f"{self.num_travelers} traveler(s)"
        if self.accessibility_needs:
            return f"{base}. Accessibility needs: {', '.join(self.accessibility_needs)}"
        return base

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


class DiscoveryRequest(BaseModel):
    """Request for destination discovery used when user uses the surprise me mode in Search tab ('Surprise Me' mode)."""

    origin: str = Field(..., description="Departure city or airport")
    budget_usd: float | None = Field(None, ge=0, description="Total budget in USD")
    departure_date: date = Field(..., description="Departure date")
    return_date: date | None = Field(None, description="Return date")
    nationality: str = Field(..., description="Traveler nationality")
    interests: list[str] = Field(default_factory=list)
    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)
    seniors: int = Field(default=0, ge=0)
    infants: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def resolve_origin_iata(self) -> "DiscoveryRequest":
        self.origin = _resolve_iata(self.origin)
        return self
