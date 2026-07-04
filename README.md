# ✈️ Travel Planner

> Plan your entire trip in under 30 seconds — flights, hotels, activities, visa rules, packing list, emergency contacts, and a day-by-day itinerary, all in one place.

**[→ Open the App](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)** &nbsp;|&nbsp; **[→ Read the Docs](https://rupakc.github.io/travel-planner/)**

---

## What is it?

Travel Planner is an AI-powered trip planning app. You tell it where you want to go, when, and what you're into — and it does the rest. Instead of spending hours jumping between tabs to check visa requirements, compare hotels, find activities, and piece together a schedule, you get everything in one structured, streaming response.

The app uses a team of specialist AI agents that all run at the same time. Results start appearing on screen within seconds and keep arriving as each agent finishes — you're never staring at a spinner waiting for everything to load at once.

---

## What you get

### Plan your trip
- **Flights** — typical routes, airlines, price ranges, and booking timing advice
- **Hotels** — neighbourhood breakdowns and accommodation options across all budget levels
- **Activities** — things to do, ranked by how well they match your stated interests
- **Places to See** — must-visit landmarks, temples, museums, and viewpoints with ratings and links
- **Day-by-day Itinerary** — a full schedule that logically groups your activities and accommodation
- **Multi-city journeys** — enter ordered stops (Paris → Rome → Barcelona) and get flights **per leg** (pick one per leg with a running total), plus hotels, activities, weather, and everything else covering **every** stop in your exact order, each item tagged with its 📍 city
- **What's On** — festivals, concerts, exhibitions, and sports events happening during your exact dates, flagged if they'll disrupt your plans (or make them better)

### Know before you go
- **Visa Requirements** — entry rules for your nationality, what documents you need, and how to apply
- **Safety & Emergency Card** — local police, ambulance, and fire numbers; nearest international hospitals; your country's embassy; 10 survival phrases in the local language; and local laws to be aware of
- **Travel Tips** — cultural etiquette, safety advice, health notes, and practical local knowledge
- **Weather** — day-by-day forecast for your travel dates; multi-city trips show each stop only for the days you're there
- **Itinerary Health Check** — an adversarial AI review of the finished plan that flags pacing problems, timing clashes, visa deadlines, weather conflicts, and budget overruns
- **Layover Optimizer** — long connection? Get a realistic timed excursion plan, transit visa notes, and whether leaving the airport is worth it
- **Packing List** — a personalised checklist based on your destination, weather, and planned activities, with essential items flagged

### Travel smart
- **SIM Cards & eSIMs** — which local carrier to get, data plan options, and where to buy
- **Currency & Money** — exchange rate guidance, whether to use cards or cash, ATM tips
- **Getting Around** — airport transfer options, public transport, ride-hailing, and intercity travel
- **Flight Price Advisor** — whether current prices are above or below typical for your route, and when to book

### Discover where to go
- **Surprise Me** — don't have a destination yet? Describe your budget and interests and get 5 personalised destination suggestions with visa status, cost estimates, and flight durations
- **Travel Confidence Score** — an instant read on how easy your chosen trip is: visa complexity, safety, English friendliness, infrastructure quality, and cost vs your budget

### Organise and save
- **My Plan** — select the flights (one per leg on multi-city trips), hotel, activities, and other items you want, see a running cost total, name your plan, and save it to come back to later
- **Timeline View** — see your itinerary as a visual morning / afternoon / evening grid, with weather for each day
- **Shareable Trip Card** — every saved plan gets a public share page with the complete trip (flights per leg, hotel, full itinerary with your notes, all picks) — downloadable as a single full-page PNG
- **Chat** — a conversational travel advisor that answers questions instantly from its own expertise, plans full trips on request with live per-section progress, asks targeted clarifying questions, and re-runs only the affected sections when you say "make it cheaper"

### Personalised to you
- **Taste Graph** — the app learns your style from what you actually select (non-stop flights, boutique hotels, food-first activities) and ranks matching options higher on every future search — no forms to fill
- **Serendipity dial** — slide between world-famous classics and hidden local gems
- **Pace & traveler mix** — relaxed/balanced/packed days; adults, children, seniors, and infants (plus accessibility needs) shape every recommendation

---

## Try it now

The app is live and free to use:

**[https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)**

Log in with the credentials you were given, or contact the admin to create an account.

---

## How it works

When you submit a search, the app runs three phases back-to-back — you start seeing results within a second and they keep arriving for the next 15–30 seconds:

```
You submit: destination, dates, budget, nationality, interests
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│  PHASE 0 — Instant (< 1 second)                              │
│                                                             │
│  Pre-computed lookup tables — no AI needed:                 │
│  ├─ Visa category for your nationality                      │
│  ├─ SIM card options for the destination                    │
│  ├─ Country travel tips                                     │
│  ├─ Emergency numbers (police, ambulance, fire)             │
│  ├─ Getting around basics                                   │
│  └─ Travel Confidence Score (safety, visa, budget, infra)   │
│                                                             │
│  These appear on screen immediately while agents load.      │
└─────────────────────────────────────────────────────────────┘
        │
        ▼ (Phase 0 already visible in browser)
┌─────────────────────────────────────────────────────────────┐
│  PHASE 1 — 12 AI agents running in parallel (8–15 seconds)  │
│                                                             │
│  Each agent runs at the same time and streams its result    │
│  the moment it finishes — you don't wait for all 12:        │
│                                                             │
│  ✈  FlightsAgent      🏨 HotelsAgent                       │
│  🎯 ActivitiesAgent   📍 PlacesAgent                       │
│  📄 VisaAgent         📱 SimAgent                          │
│  💡 TipsAgent         💱 ForexAgent                        │
│  🚌 GettingAroundAgent 🌤 WeatherAgent                     │
│  🛡  EmergencyCardAgent 🎪 EventsAgent                      │
│                                                             │
│  + 2 deferred agents (start as soon as their inputs land):  │
│  💰 PricingAdvisorAgent — triggers when ≥ 3 flight prices   │
│  🎒 PackingListAgent    — triggers when activities + weather │
│                                                             │
│  Static-backed agents (visa, sim, tips, emergency, etc.):   │
│  if AI fails → Phase 0 static data stays on screen         │
└─────────────────────────────────────────────────────────────┘
        │
        ▼ (Phase 1 results streaming throughout)
┌─────────────────────────────────────────────────────────────┐
│  PHASE 2 — Itinerary synthesis (5–15 seconds)               │
│                                                             │
│  ItineraryAgent reads hotels + ranked activities and        │
│  builds a structured day-by-day plan. Starts as soon as     │
│  both inputs are ready. 60s timeout with template fallback. │
│                                                             │
│  Then StressTestAgent audits the finished itinerary for     │
│  pacing, timing, visa, weather, and budget problems.        │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
  Complete trip plan in the browser
```

**Why results appear so fast:** Phase 0 uses lookup tables (no AI calls) and appears in under a second. Phase 1 agents all run simultaneously — the page fills in section by section as each agent finishes, rather than making you wait for the slowest one. This is done via Server-Sent Events (SSE), with a dedicated Web Worker parsing the stream off the main thread so the UI stays smooth throughout.

**Multi-city trips** run the same pipeline with per-city smarts: trip days are split across stops proportionally, flights are searched with one parallel query per leg (with retry and AI fallback for legs the search API can't serve), each specialist carries per-city minimum quotas, and both backend and frontend enforce your exact stop order in every section. See [Multi-City Trips](docs/Multi-City-Trips.md).

**Chat answers differently:** topic questions in chat are answered straight from the model's own knowledge — instant, no agents — and the specialist pipeline only steps in if the model can't answer at all, or when you ask for a full plan. See [Chat Assistant](docs/Chat-Assistant.md).

---

## For developers

### Quick start (local)

```bash
git clone https://github.com/rupakc/travel-planner.git
cd travel-planner

# Set your API key and admin password
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY and ADMIN_PASSWORD

# Start everything
./start.sh

# Open
open http://localhost:5174
```

### Or with Docker

```bash
cp backend/.env.example .env
docker compose up
open http://localhost:8080
```

### Key environment variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Anthropic API key — powers all AI agents |
| `ADMIN_PASSWORD` | Yes | Password for the built-in admin account |
| `JWT_SECRET_KEY` | Yes | Secret used to sign login tokens (generate randomly) |
| `SERPER_KEY` | Optional | Serper.dev API key for richer Places to See data |
| `BACKUP_BUCKET` | Optional | GCS bucket name for automatic database backups |

### Run tests

```bash
# Backend
cd backend && pytest --cov=app --cov-fail-under=70

# Frontend
cd frontend && npx vitest run
```

### Deploy to GCP

See the [Deployment Guide](DEPLOYMENT.md) for the full step-by-step.

---

## Documentation

| | |
|---|---|
| [Project homepage](https://rupakc.github.io/travel-planner/) | Feature overview and how it works |
| [Agent System](docs/Agent-System.md) | How the AI agents work |
| [Multi-City Trips](docs/Multi-City-Trips.md) | Per-leg flights, day allocation, stop-order guarantees |
| [Chat Assistant](docs/Chat-Assistant.md) | Knowledge-first answering, planning, refinement |
| [Personalization](docs/Personalization.md) | Taste Graph, serendipity dial, preferences |
| [Plans & Sharing](docs/Sharing-and-Plans.md) | My Plan drawer, saved plans, shareable PNG card |
| [API Reference](docs/API-Reference.md) | All REST endpoints |
| [Setup Guide](docs/Setup-and-Installation.md) | Local dev setup |
| [Configuration](docs/Configuration.md) | All environment variables |
| [Deployment](DEPLOYMENT.md) | GCP Cloud Run deployment |

---

## Built with

- **AI** — [Anthropic Claude](https://anthropic.com) via the Agent SDK, 21 specialist agent definitions (12 parallel search agents, deferred pricing/packing agents, itinerary + adversarial health-check synthesis, chat, layover, and destination discovery)
- **Backend** — Python, FastAPI, SQLite
- **Frontend** — React, Vite, Tailwind CSS
- **Infrastructure** — Google Cloud Run, Terraform, GitHub Actions

---

## License

MIT
