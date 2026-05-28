# Travel Planner — Wiki

Welcome to the Travel Planner project wiki. This is the technical documentation for developers working on the codebase.

If you're a user looking to plan a trip, head to the **[live app](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)** or the **[project homepage](https://rupakc.github.io/travel-planner/)** instead.

---

## What the app does

Travel Planner turns a destination, travel dates, budget, and list of interests into a complete trip plan — delivered in real time, section by section, as you watch.

The core idea: instead of bouncing between a dozen tabs to piece together visa rules, SIM card options, flights, hotels, things to do, and a day-by-day schedule, you describe your trip once and a coordinated team of AI agents assembles it for you in under 30 seconds.

---

## What's in the app (current feature set)

### Search results (13 sections)
1. **Flights** — routes, airlines, price ranges, booking advice
2. **Weather** — forecast for travel dates
3. **Hotels** — neighbourhoods and accommodation tiers
4. **Activities** — things to do, scored and sorted by interest relevance
5. **Places to See** — must-visit landmarks from live Google data + Claude synthesis
6. **Visa** — entry requirements for the traveller's nationality
7. **SIM Cards** — local carrier options and eSIM availability
8. **Travel Tips** — etiquette, safety, health, and practical advice
9. **Safety & Emergency Card** — emergency numbers, embassy, hospitals, local phrases, local laws
10. **Getting Around** — local and intercity transport
11. **Forex** — currency, exchange rates, payment tips
12. **Itinerary** — day-by-day schedule (Cards view or Timeline view)
13. **Packing List** — personalised checklist saved to My Plan

### Instant overlays (Phase 0, appear within 1 second)
- **Travel Confidence Score** — safety / visa ease / budget / infrastructure, shown as a banner
- **Static emergency numbers** — instantly shown while AI enrichment runs

### Destination Discovery
- **Surprise Me** — enter only origin + budget + interests → 5 curated destination cards with visa status, cost range, weather, and flight time

### Plan management
- **My Plan drawer** — select flights, hotels, activities, packing list, SIM, tips, transport, itinerary slots; live cost total; save and reload named plans

### Chat
- Persistent conversational interface — survives tab switches, continues mid-stream
- Auto-triggers the full agent pipeline when the message is trip-planning related
- Chat map aligned visually with the Results page itinerary map

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
| [Agent System](Agent-System) | All 15 agents, BaseAgent, `.agents/*.md` format, retry logic, JSON parsing, relevance scoring |
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
