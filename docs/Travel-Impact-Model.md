# Flight Emissions (Google Travel Impact Model)

Voyager shows an estimate of each flight's CO₂e per passenger, from Google's [Travel Impact Model](https://travelimpactmodel.org) (TIM), the model behind the emissions figures in Google Flights. It is off by default (`TIM_ENABLED`, see [Configuration](Configuration.md)).

## How it works

- After the flights section has streamed, `FlightsAgent.enrich` calls `services/travel_impact.annotate`, which sends **one batched request** (`POST https://travelimpactmodel.googleapis.com/v1/flights:computeFlightEmissions`) for every flight in the result set that it doesn't already have cached. The flights section then streams again with `emissions` added. A failure, timeout (8 s) or the daily cap leaves the results unchanged.
- **Exact flights only.** TIM estimates one scheduled flight: carrier, flight number, airports and date. A non-stop leg is one flight (`AF1115`, `AF 12`). A connecting leg is the sum of its `segments` (live SerpAPI results list each flown segment with its own number and date) when every segment has a parseable flight number and the segments chain from the leg's origin to its destination. A connecting leg without that (an AI result carries only the first segment's number) gets no estimate rather than a partial one, and a result is estimated only when every leg is.
- Round trips add the outbound and return legs. Each estimated leg also carries its own `emissions` (same shape), so the [trip carbon footprint](Carbon-Footprint.md) can count one direction or one multi-city leg on its own.
- **Budget.** At most `TIM_DAILY_CAP` flights are sent per UTC day (SQLite `api_budget`, row `google_tim:<date>`). Answers, including "no estimate", are cached per flight and date for 24 h, and cache hits don't count. `/health` reports `travel_impact_model: {configured, enabled, used_today, cap, paused}`.
- **The key** is sent in the `X-Goog-Api-Key` header, never in a URL, and is masked in logs.

## The `emissions` field

Each estimated flight result carries:

```json
"emissions": {
  "kg_co2e_per_pax": 134,
  "cabin": "economy",
  "by_class": {"economy": 134, "premiumEconomy": 134, "business": 201, "first": 201},
  "contrails_bucket": "CONTRAILS_IMPACT_MODERATE",
  "legs": 2,
  "model_version": "3.0.2 (20261119)",
  "source": "Google Travel Impact Model",
  "attribution_url": "https://travelimpactmodel.org",
  "licence": "CC BY-SA 4.0"
}
```

Clients must feature-detect it: an older backend, a flag that is off, or an unestimated flight simply has no `emissions`.

## Attribution

TIM data is licensed CC BY-SA 4.0. The web app shows "≈ N kg CO₂e" on each estimated flight, with a tooltip giving the per-class breakdown and the credit "Emissions estimates: Google Travel Impact Model", linked.
