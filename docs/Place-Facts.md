# Place Facts

The **Place facts** card on the Results page shows short facts about each destination (each city of a multi-city trip), its state or region and its country, in five groups:

| Group | What goes in it |
|---|---|
| `historical` | Founding, former names, turning points, heritage listings |
| `fun` | Light curiosities. The crawler writes none, so this group is always AI-suggested |
| `popular` | What the place is known for: nicknames, symbols, population, landmarks |
| `unbelievable` | Records and superlatives (highest, oldest, largest) and real oddities |
| `little_known` | Name origins, twin towns, odd borders, local history most visitors miss |

Facts come from two places, and the card always says which:

- **Sourced facts from the crawler** (`origin: "crawler"`). Each one shows its source line: source name and link, "as of" date and the licence attribution. See [Crawler Data](Crawler-Data.md).
- **AI-suggested facts** (`origin: "ai"`). The `place_facts` agent writes them from model knowledge, and only for groups that have no sourced fact. The crawler produces no `fun` facts, so the `fun` group of every place is filled by the agent (nothing assumes a crawler `fun` fact exists; one would simply be shown like any other sourced fact). They are labelled "AI-suggested, not verified" and never carry a source or a link. The model is told never to write one, and the server drops any URL or source name it sends anyway.

The feature is on by default (`PLACE_FACTS_ENABLED=true`). `GET /api/config` reports it as `features.place_facts` (`1` or `0`). When it is off, `/api/search` sends no `facts` events and `POST /api/place-facts` answers `404 place_facts_disabled`.

## How it runs

1. **Places come from our own place data.** `resolve_place` turns each destination into its GeoNames id, its first-level division (`admin1.csv`) and its country, so no model resolves a place. An airport pick ("TYO — Tokyo, Japan") is resolved as "Tokyo, Japan".
    - **A country** typed as the destination ("Japan", "Singapore", "Georgia"; every comma part must name the same country, so "Georgia, USA" is the state) is only the country, not the city its main airport serves.
    - **A city's region** is left out when it is the city itself: a city-state or capital district (a short list in `CITY_ADMIN1`: Tokyo, Berlin, Vienna, DC, Prague and others), a region that names the city inside it ("State of Berlin"), or a same-named region where the city holds at least 90 % of the region's population in our place data. A same-named state that is its own place keeps its entry (São Paulo, Rio de Janeiro, Kyoto Prefecture, New York State). A region named like the country is never repeated.
    - **A division** typed as the destination ("Florida") becomes a region.
    - **A curated destination hint** with no GeoNames id gets one from our own data when it can: the town with that own name in that country (at least 15,000 people: Kyoto → city 1857910 and its prefecture), else a notable feature so named (Santorini → a `place` with the island's id). Otherwise ("Bali") it is a `place` with no id, matched by name.
2. **Phase 0 (crawler).** When the crawler is configured, the backend calls `GET /v1/facts?geonames_id=<city>` for each city and `GET /v1/facts?country=<ISO2>` (up to 2 pages of 100) for each country, all at the same time. Places with a GeoNames id (cities and resolved hints) also get their own `geonames_id` query. The country page is split into the country's own facts (`admin_level: country`, or a Factbook fact that names only the country), the region's facts and the city's facts (same GeoNames id). **Near-duplicates** among a place's country facts are dropped: the Factbook and Wikidata often both give the same quantity (area, highest or lowest point). Two facts are the same when they have the same group, `quantity.unit` and record scope (`rank_scope` without its place name, so "highest point of Germany" matches "highest point of Federal Republic of Germany") and their values are within 1 %. The Wikidata `structured` fact is kept; another is kept only when its figure differs. A region or `place` matches an item by the same name; a name that only starts with it ("Victoria Park" for Victoria) counts only when the crawler marks the item `admin_level: admin1`. As soon as the crawler answers with at least one fact, the `facts` section is streamed with `source: "crawler"`. The UI shows it with the "Enhancing…" status.
3. **Phase 1 (AI).** The `place_facts` agent runs with the other specialists and waits for the same crawler fetch. It lists the empty groups per place and asks the model for up to 3 facts per empty group (2 on a multi-city trip). If every group already has sourced facts, no model call is made. The merged section is streamed with `source: "ai"`.
4. **Fallback.** If the agent fails, the crawler facts stay: the agent returns them. In `/api/search` a `facts` error is **never sent** (model failure, `no_facts`, `no_place`, timeout): the card stays hidden, or keeps the crawler facts, and the run stays cacheable, since the section is optional. The web app marks a crawler-only card done when the stream ends.

The crawler is optional. Off, down or without facts for the trip, the section is AI-only. An older crawler without `/v1/facts` answers `404`, which counts as no facts.

## Licence rules

These follow the rules in [Crawler Data](Crawler-Data.md#licences):

- Every crawler fact keeps its `citation`: `{source_id, name, publisher, url, as_of, licence, attribution, licence_url, conflict}`. The UI shows it with the fact, in the card, in My Plan and in the printed plan.
- **Only our own sentences are shown.** A fact's `text_origin` must be `templated` (our template over typed fields) or `rewritten` (our rewrite of a source sentence). Any other value, or none, is dropped: the crawler no longer serves source text as written (it dropped its Wikipedia hook reader), and an origin this client does not know is never shown.
- **Share-alike facts** keep their attribution and are never merged into our wording or sent to a model.
- **AI-blocked sources** (`ai_bot_blocked: true`, the source's robots.txt blocks AI bots) are not shown at all: the design note keeps such sources to title + link only, and a fact item has no title, so it is dropped.
- Only facts whose record says `llm_ok: true`, whose licence is `open` or `api_terms`, and that are not in conflict are given to the model. They are wrapped as **untrusted reference data** ("facts we already show — do not repeat them"), so the model does not repeat them.
- A fact in another language is shown when it is in the reader's language. Otherwise its ingest-time English translation (`text_en`) is shown, labelled "Machine-translated from the source language". Facts in any other language are skipped.
- **Languages.** A fact's `lang` is the language of the text as shown (`en` for a machine translation). `value_lang` (optional, BCP 47 or `und`) is the language of a quoted value in the text: an official name, nickname or motto (`The official name of Germany is “Bundesrepublik Deutschland”.`). Both are passed through and may be missing (an older crawler); anything that is not a language tag becomes `null`.
- At most 4 crawler facts per group and place. Structured and corroborated facts come first.

### Crawler contract

`GET /v1/facts` (`geonames_id`, `wikidata_qid`, `country`, `fact_type`, `limit`, `cursor`) answers `{items, next_cursor}`. Each item:

| Field | Notes |
|---|---|
| `id` | Record id (our fact id is `c:` + it) |
| `place` | `{geonames_id, wikidata_qid, admin_level, country, name, name_lang}`; a bare Factbook country gets the Wikidata country's id and QID |
| `fact_type` | `historical`, `fun`, `popular`, `unbelievable`, `little_known` (the crawler writes no `fun` facts) |
| `text`, `lang`, `text_en` | One sentence in our own words (≤ 280 characters), its language, the ingest-time English translation |
| `value_lang` | Language of a quoted value in `text`, optional |
| `text_origin` | `templated` or `rewritten` |
| `llm_ok` | Whether the text may be given to a model (false for share-alike and AI-reserved sources) |
| `date_ref`, `quantity` | Year or date; `{value, unit, rank_scope}` or `null` |
| `source` | `{source_id, url, name, publisher, source_class, sourced}` |
| `licence` | `{class, spdx, attribution, url}` |
| `as_of`, `confidence`, `ai_bot_blocked`, `updated_at` | Edition or crawl date; `structured`, `extracted` or `corroborated`; robots.txt blocks AI bots; last update |

## Section shape

```json
{
  "places": [
    {
      "key": "city:2950159", "scope": "city", "name": "Berlin",
      "country": "DE", "country_name": "Germany",
      "destination": "Berlin, Germany", "geonames_id": 2950159,
      "groups": {
        "historical": [
          {"id": "c:1234", "fact_type": "historical", "text": "Berlin was founded in 1237.",
           "origin": "crawler", "source": "crawler", "date_ref": "1237",
           "lang": "en", "value_lang": null,
           "machine_translated": false, "confidence": "structured",
           "citation": {"source_id": "od-wikidata-entitydata", "name": "Wikidata",
                        "publisher": "Wikidata contributors (Wikimedia Foundation)",
                        "url": "https://www.wikidata.org/wiki/Q64#P571", "as_of": "2026-11-20",
                        "licence": "open", "attribution": "Wikidata (CC0 1.0)",
                        "licence_url": null, "conflict": false}}
        ],
        "fun": [],
        "popular": [],
        "unbelievable": [
          {"id": "a:3f9c0b1d2e4a", "fact_type": "unbelievable", "text": "…",
           "origin": "ai", "source": "ai", "verified": false, "citation": null}
        ],
        "little_known": []
      }
    }
  ],
  "fact_types": ["historical", "fun", "popular", "unbelievable", "little_known"],
  "counts": {"crawler": 1, "ai": 1},
  "verification": {"level": "partial", "...": "..."}
}
```

`scope` is `city`, `place` (a curated destination that is not one of our towns; `geonames_id` is set when it is a known feature), `region` or `country`. Two cities in one country share one country entry. AI fact ids are a hash of the place, group and text. Crawler fact ids are `c:` plus the crawler's record id.

**Verification chip** (`services/verification.py`): a fact counts as sourced only when it is a crawler fact with a source link (`citation.url`) and no `conflict`. `verified` when every fact is sourced, `partial` when some are, `unverified` when none are (AI-suggested, or a source without a link such as a Factbook fact).

## API

`POST /api/place-facts` takes the same body as `/api/search` (including `locale` and multi-city `destinations`) and returns the section above with `verification`. It is in the `light_ai` rate-limit bucket. Errors: `404 place_facts_disabled`, `422` for a bad body, and the usual `{"error", "error_code"}` object when the model fails and the crawler had nothing (for example `ai_limit`).

In `/api/search`, the stream sends `agent_status` for `facts` at start, then `facts` with `source: "crawler"` (Phase 0, only when the crawler answered with facts), then `facts` with `source: "ai"` (left out when the AI pass failed). A `facts` error is never streamed, so it never stops a run from being cached. The search cache key is unchanged. `/api/search/sync` includes `facts` too.

## Web app

`frontend/src/components/PlaceFactsSection.jsx` is shown as its own card after Tips. It renders only when the stream sent a `facts` section with at least one fact, so with an older backend it stays hidden. There are place chips (multi-place trips) and group tabs with counts. Each crawler fact has its source line (`SourceLine` from `OfficialData.jsx`). Each AI fact has the "AI-suggested, not verified" label, and a note under the list explains it. Every fact can be added to **My Plan** (`selections.place_facts`: `{id, text, fact_type, place, origin, lang, value_lang, citation}`, where `citation` is null for AI facts). The drawer and the plan view (`SelectedFact`) and the printed plan show each fact as it was shown in the card: a crawler fact with its source link, as-of date and licence attribution (linked to the licence); AI facts with the AI label. The text carries `lang` when known, and a single quoted value (“…”) is wrapped in a `<span lang>` of its `value_lang` (`utils/placeFactText.js`; `und` and invalid tags are left out). A plan saved with the old `quote` flag shows that fact as plain text with its attribution. Every link goes through `safeUrl`. Shared plans leave them out, because the share whitelist does not include them. Strings are in the `results`, `sections` and `plan` namespaces in all 7 languages. The interactive elements carry `data-tid` (`results.facts.place`, `results.facts.group`, `results.fact.add`, `drawer.remove.place_facts`, `plan.remove-place-facts`; source links use `results.official.source`). No new telemetry events are added.

Android and iOS do not show the section yet (see [Feature Parity](Feature-Parity.md)). They ignore the unknown `facts` event.

## Code and tests

- `backend/app/services/crawler_client.py`: `place_facts(geonames_id=, wikidata_qid=, country=, fact_type=, limit=, pages=)`. It never raises, uses a 1-hour cache, and shares the breaker and timeout with every other crawler read.
- `backend/app/services/place_facts.py`: place scopes, crawler mapping, the model reference block, `merge_ai`.
- `backend/app/agents/place_facts_agent.py` and `.agents/place_facts.md`.
- `backend/app/api/routes/place_facts.py`.
- `backend/tests/test_place_facts.py` (crawler as `httpx.MockTransport`, model as a patched `execute`) and `frontend/src/components/PlaceFactsSection.test.jsx`.
