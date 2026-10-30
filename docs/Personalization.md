# Personalization

Three layers tune results to the traveller: saved **preferences**, per-search **settings**, and the learned **Taste Graph**.

---

## Preferences

Saved per account (`GET/PUT /api/preferences`, `frontend/src/pages/PreferencesPage.jsx`):

- **Travel Budget**: Budget, Mid-range or Luxury (pre-fills the Search budget as 1000, 3000 or 8000 USD).
- **Identity**: nationality and current residence (used as the default departure city).
- **Documents**: residence permits and existing visas.
- **Travel Style**: interests, the traveller mix and accessibility needs.

**Two-way binding** (`frontend/src/context/AuthContext.jsx`): saved preferences pre-fill the Search form on load, and submitting a search writes its fields back to preferences. The app therefore always remembers the latest defaults. A loaded recent search takes precedence over the pre-fill.

## Recent searches

Every submitted search, from the Search form or from the Results page's search panel, is saved to the account (`/api/recent-searches`): the newest 8, with identical searches merged (interest order ignored). They appear in a collapsible strip above the Search form; see [Trip Planning Features](Trip-Planning-Features.md#recent-searches).

## Per-search settings

These are fields of `TravelSearchRequest` (`backend/app/schemas/request.py`) that agents receive in their prompts:

- **Serendipity** (`serendipity`, 0.0–1.0), the Search form's "Discovery style" slider: Famous classics, Balanced mix, Hidden gems. At the hidden-gems end, agents prefer local favourites and mark results `hidden_gem: true`.
- **Pace** (`pace`: relaxed, balanced or packed) controls how densely the itinerary fills each day. It has no control on the Search form: the "Slow it down" remix sets it to relaxed, and API callers can set it directly.
- **Traveller mix**: adults (18–64), seniors (65+), children (5–17), infants (0–4). It shapes fare notes, hotel suitability and activity choices.
- **Accessibility needs**: wheelchair, visual, hearing, cognitive. They are passed into every agent prompt.
- **Interests**: activities get a model-assigned relevance score (0.0–1.0) and are sorted by it.

## Taste Graph

The Taste Graph (`backend/app/db/taste_db.py`) learns a user's style from what they **save into plans**, with no forms to fill.

1. Saving a plan (`POST`/`PUT /api/plans`) mines its selections for signals (`extract_signals`): flight style (non-stop or cheapest, per selected leg), hotel tier and type, activity categories and budget band. They are stored in the `taste_signals` table.
2. `derive_taste_context()` condenses the signals into a short sentence, for example "Prefers non-stop flights, mid-range boutique hotels, food and history activities."
3. On `/api/search` (with a valid token), `/api/chat` and their specialist runs, the server sets `TravelSearchRequest.taste_context` from the user's profile; a value sent by the client is ignored.

Agents use it to **rank matching options higher**, never to filter options out, so all budget tiers still appear. Because `taste_context` is part of the search cache key, cached results are per profile and never leak between users.

The Preferences page shows what has been learned (`GET /api/taste-profile`) and has a Reset button (`DELETE /api/taste-profile`).
