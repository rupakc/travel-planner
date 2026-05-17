from pydantic import BaseModel
from typing import Optional, Any


class FlightResult(BaseModel):
    airline: Optional[str] = None
    flight_number: Optional[str] = None
    origin: Optional[str] = None
    destination: Optional[str] = None
    departure_time: Optional[str] = None
    arrival_time: Optional[str] = None
    duration_minutes: Optional[int] = None
    price_usd: Optional[float] = None
    stops: Optional[int] = None
    booking_url: Optional[str] = None
    source_snippet: Optional[str] = None


class FlightsResponse(BaseModel):
    results: list[FlightResult] = []


class HotelResult(BaseModel):
    name: Optional[str] = None
    star_rating: Optional[float] = None
    price_per_night_usd: Optional[float] = None
    total_price_usd: Optional[float] = None
    location: Optional[str] = None
    amenities: list[str] = []
    booking_url: Optional[str] = None
    review_score: Optional[float] = None
    source_snippet: Optional[str] = None


class HotelsResponse(BaseModel):
    results: list[HotelResult] = []


class ActivityResult(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    duration_hours: Optional[float] = None
    price_usd: Optional[float] = None
    location: Optional[str] = None
    booking_url: Optional[str] = None
    similarity_score: Optional[float] = None
    source: Optional[str] = None


class ActivitiesResponse(BaseModel):
    results: list[ActivityResult] = []


class VisaRequirement(BaseModel):
    visa_type: Optional[str] = None
    max_stay_days: Optional[int] = None
    requirements: list[str] = []
    processing_time: Optional[str] = None
    fee_usd: Optional[float] = None
    official_url: Optional[str] = None
    confidence: Optional[str] = None
    notes: Optional[str] = None


class VisaResponse(BaseModel):
    requirement: Optional[VisaRequirement] = None


class NetworkQuality(BaseModel):
    speed: Optional[str] = None
    coverage_rating: Optional[str] = None
    coverage_description: Optional[str] = None


class SimPlan(BaseModel):
    provider: Optional[str] = None
    plan_name: Optional[str] = None
    data_gb: Optional[float] = None
    validity_days: Optional[int] = None
    price_usd: Optional[float] = None
    purchase_location: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None
    network_quality: Optional[NetworkQuality] = None


class SimResponse(BaseModel):
    plans: list[SimPlan] = []


class Tip(BaseModel):
    category: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    severity: Optional[str] = None
    source_url: Optional[str] = None


class TipsResponse(BaseModel):
    tips: list[Tip] = []


class ItinerarySlot(BaseModel):
    time_of_day: str
    activity: str
    location: Optional[str] = None
    duration_hours: Optional[float] = None
    notes: Optional[str] = None
    estimated_cost_usd: Optional[float] = None


class ItineraryDay(BaseModel):
    day_number: int
    date: Optional[str] = None
    theme: Optional[str] = None
    slots: list[ItinerarySlot] = []
    daily_estimated_cost_usd: Optional[float] = None


class ItineraryResponse(BaseModel):
    days: list[ItineraryDay] = []
    total_estimated_cost_usd: Optional[float] = None


class TransportOption(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    scope: Optional[str] = None
    description: Optional[str] = None
    coverage: Optional[str] = None
    price_info: Optional[str] = None
    operating_hours: Optional[str] = None
    tips: Optional[str] = None
    booking_url: Optional[str] = None
    tourist_pass: Optional[str] = None


class GettingAroundResponse(BaseModel):
    options: list[TransportOption] = []


class ExchangeRate(BaseModel):
    from_currency: Optional[str] = None
    to_currency: Optional[str] = None
    rate: Optional[float] = None
    description: Optional[str] = None
    trend: Optional[str] = None


class ExchangeLocation(BaseModel):
    type: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    rating: Optional[str] = None
    fees: Optional[str] = None
    tip: Optional[str] = None


class CardAcceptance(BaseModel):
    visa_mastercard: Optional[str] = None
    amex: Optional[str] = None
    contactless: Optional[str] = None
    digital_wallets: Optional[str] = None
    surcharges: Optional[str] = None


class CashAdvice(BaseModel):
    cash_dependency: Optional[str] = None
    recommendation: Optional[str] = None
    denominations: Optional[str] = None
    bring_usd_eur: Optional[str] = None


class AtmInfo(BaseModel):
    availability: Optional[str] = None
    networks: Optional[str] = None
    withdrawal_limit: Optional[str] = None
    fees: Optional[str] = None
    best_option: Optional[str] = None


class TippingInfo(BaseModel):
    expected: Optional[bool] = None
    description: Optional[str] = None


class MoneyTip(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None


class LocalCurrency(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    symbol: Optional[str] = None


class ForexResponse(BaseModel):
    local_currency: Optional[LocalCurrency] = None
    exchange_rates: list[ExchangeRate] = []
    exchange_locations: list[ExchangeLocation] = []
    card_acceptance: Optional[CardAcceptance] = None
    cash_advice: Optional[CashAdvice] = None
    atm_info: Optional[AtmInfo] = None
    tipping: Optional[TippingInfo] = None
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
