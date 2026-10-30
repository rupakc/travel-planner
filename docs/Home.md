# Travel Planner — Developer Docs

Travel Planner turns a route, travel dates, a budget and a list of interests into a complete trip plan. A team of Claude agents builds the plan, and the results stream to the browser section by section as each agent finishes.

These pages are the technical documentation for people working on the code. The project is open source under the MIT License (`LICENSE` at the repo root).

> **No hosted instance.** The production deployment on Google Cloud Run was decommissioned on 2026-08-30: the GCP project was deleted and the old app URLs no longer work. To try the app, run it locally with `./start.sh` or `docker compose up --build` (see [Setup and Installation](Setup-and-Installation.md)). [Deployment](Deployment.md) explains how to bring a hosted copy back.

---

## What the app does

- **Search** in three modes: *I know where I'm going* (one city or up to 3 stops on the way), *Surprise me* (5 suggested destinations), and *Compare* (2–3 destinations side by side). Recent searches are kept per user.
- **Results**: 16 sections (flights, weather, hotels, activities, places to see, free walking tours, events, visa, SIM, tips, emergency card, getting around, forex, itinerary, trip health check and packing list), each with a source-verification label.
- **Planning tools** on the Results page: a best-value package, a client-side budget planner, an opt-in fare calendar with Google Flights price insights, Trip Remix presets, and an itinerary you can rearrange by drag-and-drop with estimated times, edits, notes and a re-check.
- **My Plan** drawer: pick items into a plan, see the cost breakdown, export to calendar (`.ics`) or print/PDF, save plans and share them by public link.
- **Chat**: a travel advisor that answers from model knowledge and can plan a whole trip in the conversation.
- **Personalization**: saved preferences bound two ways to the Search form, and a Taste Graph learned from saved plans.
- **Accounts**: admin-created users (no self-registration), an admin page, a feedback widget and per-user rate limits.

[Trip Planning Features](Trip-Planning-Features.md) describes each of these in detail.

---

## How a search works, in brief

1. **Phase 0 (instant).** Static lookup tables yield visa, SIM, tips, getting-around and forex results, the Travel Ease confidence grade and the emergency card, all marked `source: "static"`.
2. **Phase 1 (parallel AI).** Thirteen specialist agents run concurrently and stream their results as they finish. For the six static-backed agents (visa, sim, tips, getting_around, forex, emergency_card) an AI failure is suppressed, so the static data stays on screen. Two deferred agents, packing list and pricing advisor, start as soon as their inputs are ready.
3. **Phase 2.** The itinerary agent starts once activities and hotels are in (60 s timeout, template fallback). When the itinerary is final, the stress-test agent audits it.

Every specialist agent uses Claude Haiku 4.5 through `BaseAgent`. Chat uses Claude Sonnet 4.6 for conversational answers. See [Architecture](Architecture.md) and [Agent System](Agent-System.md).

---

## Pages

| Page | What it covers |
|---|---|
| [Setup and Installation](Setup-and-Installation.md) | Running locally with `start.sh`, by hand, or with Docker Compose; first login |
| [Configuration](Configuration.md) | Every environment variable and its default |
| [Architecture](Architecture.md) | Components, orchestration phases, SSE, persistence, caching, rate limits |
| [Agent System](Agent-System.md) | The 22 agent definitions, `BaseAgent`, static fallbacks, verification |
| [Trip Planning Features](Trip-Planning-Features.md) | Search modes, every Results section, planning tools, itinerary, My Plan |
| [Multi-City Trips](Multi-City-Trips.md) | Stops, day allocation, per-leg flights, per-city coverage |
| [Chat Assistant](Chat-Assistant.md) | Routing, knowledge-first answers, comprehensive planning, refinement |
| [Personalization](Personalization.md) | Preferences, recent searches, search dials, Taste Graph |
| [Sharing and Plans](Sharing-and-Plans.md) | My Plan drawer, saved plans, export, share links |
| [Place and Airport Data](Place-and-Airport-Data.md) | OurAirports and GeoNames data, licences, how typed places resolve to airports |
| [Frontend](Frontend.md) | React app structure, routing, contexts, workers, utilities |
| [API Reference](API-Reference.md) | Every endpoint, SSE event types, rate-limit buckets |
| [Testing and CI](Testing-and-CI.md) | Test commands, lint gates, GitHub Actions workflows |
| [Deployment](Deployment.md) | Current state (decommissioned) and how to redeploy from `infrastructure/` |
| [Contributing](Contributing.md) | Workflow, code style, adding an agent |
| [Changelog](Changelog.md) | Merged PRs by theme, and the history before them |

---

## Links

- [GitHub repository](https://github.com/rupakc/travel-planner)
- [Project homepage](https://rupakc.github.io/travel-planner/)
- [Open an issue](https://github.com/rupakc/travel-planner/issues)

Place data contains data from GeoNames (geonames.org), CC BY 4.0. Airport data comes from OurAirports (public domain). See [Place and Airport Data](Place-and-Airport-Data.md).
