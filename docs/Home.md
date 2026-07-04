# Travel Planner — Wiki

Welcome to the Travel Planner project wiki. This is the technical documentation for developers working on the codebase.

If you're a user looking to plan a trip, head to the **[live app](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)** or the **[project homepage](https://rupakc.github.io/travel-planner/)** instead.

---

## What the app does

Travel Planner turns a destination, travel dates, budget, and list of interests into a complete trip plan — delivered in real time, section by section, as you watch.

The core idea: instead of bouncing between a dozen tabs to piece together visa rules, SIM card options, flights, hotels, things to do, and a day-by-day schedule, you describe your trip once and a coordinated team of AI agents assembles it for you in under 30 seconds.

---

## What's in the app (current feature set)

### Search results (15 sections)
1. **Flights** — live prices via Google Flights (SerpAPI) with AI fallback; **per-leg search on multi-city trips** with one pick per leg
2. **Weather** — day-by-day forecast for the travel dates; per-stay forecasts grouped by city on multi-city trips
3. **Hotels** — neighbourhoods and accommodation across four budget tiers (≥ 3 per city on multi-city)
4. **Activities** — things to do, scored and sorted by interest relevance (≥ 5 per city)
5. **Places to See** — must-visit landmarks from live Google data + Claude synthesis (4–6 per city)
6. **What's On (Events)** — festivals, concerts, exhibitions during the trip dates, with disruption flags
7. **Visa** — entry requirements for the traveller's nationality (every country on multi-country routes)
8. **SIM Cards** — local carrier options and eSIM availability
9. **Travel Tips** — etiquette, safety, health, and practical advice
10. **Safety & Emergency Card** — emergency numbers, embassy, hospitals, local phrases, local laws
11. **Getting Around** — local and intercity transport (per-city + inter-city hops on multi-city)
12. **Forex** — currency, exchange rates, payment tips
13. **Itinerary** — day-by-day schedule (Cards or Timeline view), always in the user's stop order
14. **Itinerary Health Check** — adversarial stress-test of the finished plan (pacing, timing, visa, weather, budget)
15. **Packing List** — personalised checklist saved to My Plan

Every result on a multi-city trip carries a 📍 city label, and all sections follow the exact stop order entered.

### Instant overlays (Phase 0, appear within 1 second)
- **Travel Confidence Score** — safety / visa ease / budget / infrastructure, shown as a banner
- **Static emergency numbers** — instantly shown while AI enrichment runs

### Destination Discovery
- **Surprise Me** — enter only origin + budget + interests → 5 curated destination cards with visa status, cost range, weather, and flight time

### Plan management
- **My Plan drawer** — select flights, hotels, activities, packing list, SIM, tips, transport, itinerary slots; live cost total; save and reload named plans

### Chat
- **Knowledge-only answers** — topic questions are answered instantly from the model's own expertise; specialist agents run only if the model fails to answer at all
- Full planning pipeline on request, with live per-section progress, targeted clarifying questions (slot memory), suggestion chips, and proactive weather/event heads-ups
- **Refinement diffing** — "make it cheaper" re-runs only the affected agents
- Persistent conversational interface — survives tab switches, continues mid-stream

### Personalization
- **Taste Graph** — learns travel style from saved-plan selections and ranks matching options higher on every search
- Serendipity dial (classics ↔ hidden gems), pace (relaxed/balanced/packed), traveler mix, accessibility needs
- Two-way preference binding between the Search form and saved Preferences

### Sharing
- **Shareable trip card** — public share page per saved plan with the complete trip, downloadable as a full-page PNG

### Accounts and admin
- JWT authentication, bcrypt passwords, forced first-login password change
- Admin panel: create/deactivate users, view and export feedback

---

## Architecture in plain English

### Three phases of a search

**Phase 0 — instant (< 1 second)**
Some data doesn't need an AI call. Visa categories, SIM basics, travel tips, transport types, emergency numbers, and the confidence score all come from lookup tables and stream to the browser before any AI agent has started.

**Phase 1 — parallel AI agents (8–15 seconds)**
Thirteen specialist Claude agents run concurrently. As each one finishes, its result streams to the browser immediately — you see flights arrive, then hotels, then activities, without waiting for everything at once. Agents with static fallbacks (visa, SIM, tips, getting around, emergency card) are fault-tolerant: if the AI call fails, the static data is retained rather than replaced with an error.

**Phase 2 — synthesis and deferred tasks (5–10 seconds after Phase 1)**
The itinerary agent runs once activities and hotels are both ready. Two deferred tasks trigger during Phase 1: the packing list starts when activities arrive and weather is done; the price advisor starts when at least 3 flight prices are available.

### Streaming
Results use Server-Sent Events (SSE). A Web Worker parses the stream off the main thread so the UI stays responsive while data is arriving. The chat interface uses a separate worker for the same reason.

### Static-first, AI-enhanced
For visa, SIM, tips, getting around, and emergency card: Phase 0 sends instant data marked as "Enhancing…". Phase 1 sends the AI-improved version. If Phase 1 fails, the Phase 0 data stays on screen — users never see an error where there was previously useful information.

---

## Wiki pages

| Page | What it covers |
|---|---|
| [Agent System](Agent-System) | All 21 agents, BaseAgent, `.agents/*.md` format, retry logic, JSON parsing, relevance scoring |
| [Multi-City Trips](Multi-City-Trips) | Per-leg flight search, day allocation, per-city coverage quotas, stop-order guarantees |
| [Chat Assistant](Chat-Assistant) | Knowledge-only answering, planning pipeline, refinement diffing, session context |
| [Personalization](Personalization) | Taste Graph, serendipity dial, pace, preferences |
| [Sharing and Plans](Sharing-and-Plans) | My Plan drawer, saved plans, shareable full-page PNG card |
| [Setup and Installation](Setup-and-Installation) | Local dev setup, Docker Compose, first login, running tests |
| [Configuration](Configuration) | Every environment variable with required/optional status and effect |
| [API Reference](API-Reference) | All REST endpoints: search, discover, chat, auth, plans, preferences, feedback, admin |
| [Frontend](Frontend) | React SPA structure, routing, AuthContext, Web Workers, key pages and components |
| [Deployment](Deployment) | GCP Cloud Run, Terraform, GitHub Actions CI/CD, SQLite backup/restore lifecycle |

---

## Quick links

- [GitHub repository](https://github.com/rupakc/travel-planner)
- [Live app](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)
- [Project homepage](https://rupakc.github.io/travel-planner/)
- [Open an issue](https://github.com/rupakc/travel-planner/issues)
