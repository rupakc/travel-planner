from pydantic import BaseModel


class FlightResult(BaseModel):
    airline: str | None = None
    flight_number: str | None = None
    origin: str | None = None
    destination: str | None = None
    departure_time: str | None = None
    arrival_time: str | None = None
    duration_minutes: int | None = None
    price_usd: float | None = None
    stops: int | None = None
    booking_url: str | None = None
    source_snippet: str | None = None


class FlightsResponse(BaseModel):
    results: list[FlightResult] = []


class HotelResult(BaseModel):
    name: str | None = None
    star_rating: float | None = None
    price_per_night_usd: float | None = None
    total_price_usd: float | None = None
    location: str | None = None
    amenities: list[str] = []
    booking_url: str | None = None
    review_score: float | None = None
    source_snippet: str | None = None


class HotelsResponse(BaseModel):
    results: list[HotelResult] = []


class ActivityResult(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    duration_hours: float | None = None
    price_usd: float | None = None
    location: str | None = None
    booking_url: str | None = None
    similarity_score: float | None = None
    source: str | None = None


class ActivitiesResponse(BaseModel):
    results: list[ActivityResult] = []


class VisaRequirement(BaseModel):
    visa_type: str | None = None
    max_stay_days: int | None = None
    requirements: list[str] = []
    processing_time: str | None = None
    fee_usd: float | None = None
    official_url: str | None = None
    confidence: str | None = None
    notes: str | None = None


class VisaResponse(BaseModel):
    requirement: VisaRequirement | None = None


class NetworkQuality(BaseModel):
    speed: str | None = None
    coverage_rating: str | None = None
    coverage_description: str | None = None


class SimPlan(BaseModel):
    provider: str | None = None
    plan_name: str | None = None
    data_gb: float | None = None
    validity_days: int | None = None
    price_usd: float | None = None
    purchase_location: str | None = None
    url: str | None = None
    snippet: str | None = None
    network_quality: NetworkQuality | None = None


class SimResponse(BaseModel):
    plans: list[SimPlan] = []


class Tip(BaseModel):
    category: str | None = None
    title: str | None = None
    body: str | None = None
    severity: str | None = None
    source_url: str | None = None


class TipsResponse(BaseModel):
    tips: list[Tip] = []


class ItinerarySlot(BaseModel):
    time_of_day: str
    activity: str
    location: str | None = None
    duration_hours: float | None = None
    notes: str | None = None
    estimated_cost_usd: float | None = None


class ItineraryDay(BaseModel):
    day_number: int
    date: str | None = None
    theme: str | None = None
    slots: list[ItinerarySlot] = []
    daily_estimated_cost_usd: float | None = None


class ItineraryResponse(BaseModel):
    days: list[ItineraryDay] = []
    total_estimated_cost_usd: float | None = None


class TransportOption(BaseModel):
    name: str | None = None
    type: str | None = None
    scope: str | None = None
    description: str | None = None
    coverage: str | None = None
    price_info: str | None = None
    operating_hours: str | None = None
    tips: str | None = None
    booking_url: str | None = None
    tourist_pass: str | None = None


class GettingAroundResponse(BaseModel):
    options: list[TransportOption] = []


class ExchangeRate(BaseModel):
    from_currency: str | None = None
    to_currency: str | None = None
    rate: float | None = None
    description: str | None = None
    trend: str | None = None


class ExchangeLocation(BaseModel):
    type: str | None = None
    name: str | None = None
    description: str | None = None
    rating: str | None = None
    fees: str | None = None
    tip: str | None = None


class CardAcceptance(BaseModel):
    visa_mastercard: str | None = None
    amex: str | None = None
    contactless: str | None = None
    digital_wallets: str | None = None
    surcharges: str | None = None


class CashAdvice(BaseModel):
    cash_dependency: str | None = None
    recommendation: str | None = None
    denominations: str | None = None
    bring_usd_eur: str | None = None


class AtmInfo(BaseModel):
    availability: str | None = None
    networks: str | None = None
    withdrawal_limit: str | None = None
    fees: str | None = None
    best_option: str | None = None


class TippingInfo(BaseModel):
    expected: bool | None = None
    description: str | None = None


class MoneyTip(BaseModel):
    title: str | None = None
    body: str | None = None


class LocalCurrency(BaseModel):
    name: str | None = None
    code: str | None = None
    symbol: str | None = None


class ForexResponse(BaseModel):
    local_currency: LocalCurrency | None = None
    exchange_rates: list[ExchangeRate] = []
    exchange_locations: list[ExchangeLocation] = []
    card_acceptance: CardAcceptance | None = None
    cash_advice: CashAdvice | None = None
    atm_info: AtmInfo | None = None
    tipping: TippingInfo | None = None
    money_tips: list[MoneyTip] = []
    source_urls: list[str] = []


class TravelSearchResponse(BaseModel):
    flights: dict = {}
    hotels: dict = {}
    activities: dict = {}
    visa: dict = {}
    sim: dict = {}
    tips: dict = {}
    getting_around: dict = {}
    forex: dict = {}
    itinerary: dict = {}
