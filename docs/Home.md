# Travel Planner

Travel Planner is an AI-powered, full-stack travel planning application that turns a destination, a date range, a budget, and a list of interests into a complete, structured trip plan — delivered in real time, section by section, as you watch.

The core idea is simple: instead of bouncing between a dozen tabs to piece together visa rules, SIM card options, flights, hotels, things to do, and a day-by-day schedule, you describe your trip once and a coordinated team of AI agents assembles it for you in under 30 seconds.

---

## Why it was built

Most AI travel assistants are just a chatbot wrapper around a language model. Ask a question, get a wall of text, ask a follow-up, get another wall of text. There is no structure, no parallel execution, no streaming — just one slow sequential request.

Travel Planner takes a different approach: it decomposes the problem into specialist agents (flights, hotels, visa, activities, SIM cards, transport, forex, tips), runs them all in parallel, streams each result back to the browser the moment it is ready, and then synthesises everything into a coherent day-by-day itinerary. The user sees information appearing in real time rather than staring at a spinner.

---

## The three-phase architecture (plain English)

**Phase 0 — Instant static data (< 1 second)**

Some information does not need an AI call. Visa categories, SIM card basics, country-level travel tips, and local transport types are pre-computed from lookup tables and sent to the browser immediately. The user sees something useful before any AI call has even started.

**Phase 1 — Eight specialist agents in parallel (8–15 seconds)**

Eight Claude-powered agents run concurrently via `asyncio.gather()`:

- **FlightsAgent** — typical routes, airlines, price ranges, booking advice
- **HotelsAgent** — neighbourhood breakdown, accommodation types, price bands
- **ActivitiesAgent** — things to do, scored for relevance to the user's stated interests using semantic similarity (sentence-transformers)
- **VisaAgent** — entry requirements, application process, processing times for the traveller's nationality
- **SimAgent** — local carriers, data plans, coverage notes
- **TipsAgent** — cultural norms, safety, etiquette, health, money
- **GettingAroundAgent** — transport options once at the destination
- **ForexAgent** — currency, exchange rate guidance, payment tips

Each agent is defined by a `.agents/{name}.md` file (YAML frontmatter + markdown system prompt). Each retries up to 4 times on failure and uses a 3-strategy JSON parsing fallback before returning a structured error.

**Phase 2 — Itinerary synthesis (5–10 seconds)**

Once the activities and hotels results are available, the ItineraryAgent generates a detailed day-by-day schedule. It has a 60-second timeout and falls back to a template-based itinerary if the model does not respond in time.

All results stream to the browser via Server-Sent Events (SSE), processed off the main thread by a Web Worker.

---

## Key features

- Real-time streaming — results appear section by section, not all at once
- 8 specialist agents running in parallel — fast and thorough
- Relevance scoring for activities — activities ranked by semantic similarity to the user's interests, not just dumped in random order
- Persistent plans — authenticated users can save and revisit plans
- Multi-user with admin controls — JWT-based auth, bcrypt passwords, forced password change on first login
- Chat mode — a follow-up chat interface that is aware of travel context
- SQLite + GCS backup — databases backed up to Google Cloud Storage every 5 minutes and on shutdown, restored automatically on startup

---

## Wiki pages

| Page | What it covers |
|---|---|
| [Architecture](Architecture) | Three-phase flow, SSE streaming, Web Worker, database backup strategy |
| [Agent System](Agent-System) | BaseAgent, `.agents/*.md` format, all 8 agents, retry + fallback logic, relevance scoring |
| [Setup and Installation](Setup-and-Installation) | Local dev setup, Docker Compose, first login, running tests |
| [Configuration](Configuration) | Every environment variable with required/optional status and effect |
| [API Reference](API-Reference) | All REST endpoints: search, chat, auth, plans, preferences, feedback, admin |
| [Frontend](Frontend) | React SPA, routing, AuthContext, SearchDataContext, Web Worker, key pages |
| [Deployment](Deployment) | GCP Cloud Run, Terraform, GitHub Actions CI/CD, SQLite/GCS lifecycle |

---

## Quick links

- [GitHub repository](https://github.com/rupakc/travel-planner)
- [Open an issue](https://github.com/rupakc/travel-planner/issues)
