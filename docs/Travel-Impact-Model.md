# Flight Emissions (Google Travel Impact Model)

Voyager shows an estimate of each flight's CO₂e per passenger, from Google's [Travel Impact Model](https://travelimpactmodel.org) (TIM), the model behind the emissions figures in Google Flights. It is off by default (`TIM_ENABLED`, see [Configuration](Configuration.md)).

## How it works

- After the flights section has streamed, `FlightsAgent.enrich` calls `services/travel_impact.annotate`, which sends **one batched request** (`POST https://travelimpactmodel.googleapis.com/v1/flights:computeFlightEmissions`) for every flight in the result set that it doesn't already have cached. The flights section then streams again with `emissions` added. A failure, timeout (8 s) or the daily cap leaves the results unchanged.
- **Exact flights only.** TIM estimates one scheduled flight: carrier, flight number, airports and date. A result is estimated only when every leg is non-stop with a parseable flight number (`AF1115`, `AF 12`). Connecting legs carry only their first segment's number, so they get no estimate rather than a partial one.
- Round trips add the outbound and return legs.
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
