# Personalization

Three layers tune results to the traveler: explicit **preferences**, per-search **dials**, and the learned **Taste Graph**.

## Preferences (explicit)

Saved per account (`/api/preferences`, PreferencesPage): home airport, nationality, residence permits, existing visas, default budget, interests, and traveler mix. Preferences **pre-fill the Search form**, and edits made on the Search form **sync back** to preferences on submit — a two-way binding, so the app always remembers your latest defaults.

## Search dials (per trip)

- **Pace** — `relaxed | balanced | packed` controls how densely the itinerary schedules each day.
- **Serendipity dial** — `0.0–1.0`: at the low end you get the famous classics; at the high end agents prioritise hidden gems and local favourites, marking each result with `hidden_gem: true/false`.
- **Traveler mix** — adults / children (5–17) / seniors (65+) / infants (0–4) shape flight fare notes, hotel suitability, and activity choices.
- **Accessibility needs** — wheelchair, visual/hearing impairment, cognitive disability — propagate into every agent prompt.

## Taste Graph (learned)

The Taste Graph (`backend/app/db/taste_db.py`) learns your style from what you actually **select into plans** — no forms to fill:

1. Every saved plan's selections are mined for signals (`extract_signals`): flight style (non-stop vs cheapest, per selected leg), hotel tier and type, activity categories, typical budget band.
2. `derive_taste_context()` compresses the signals into a short natural-language profile, e.g. *"Prefers non-stop flights, mid-range boutique hotels, food and history activities."*
3. That summary is injected server-side into `TravelSearchRequest.taste_context` for every agent prompt (client-supplied values are ignored) — and into the chat assistant's system prompt.

Agents use it to **rank matching options higher**, never to filter options out — you always see the full spread across budget tiers.

Because `taste_context` participates in result-cache keys, cached searches are per-profile and one user's taste never leaks into another's results.

## Where it shows up

| Surface | Effect |
|---|---|
| Flights | Preferred style (e.g. non-stop) ranked first |
| Hotels | Preferred tier/type ranked first — all four budget tiers still shown |
| Activities | Interest relevance scoring (0.0–1.0) plus learned category boosts |
| Itinerary | Pacing follows the pace dial; serendipity shapes the mix |
| Chat | Advisor recommendations lean toward your demonstrated taste |
