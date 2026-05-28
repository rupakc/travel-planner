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

### Know before you go
- **Visa Requirements** — entry rules for your nationality, what documents you need, and how to apply
- **Safety & Emergency Card** — local police, ambulance, and fire numbers; nearest international hospitals; your country's embassy; 10 survival phrases in the local language; and local laws to be aware of
- **Travel Tips** — cultural etiquette, safety advice, health notes, and practical local knowledge
- **Weather** — forecast for your travel dates
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
- **My Plan** — select the flights, hotels, and activities you want, see a running cost total, name your plan, and save it to come back to later
- **Timeline View** — see your itinerary as a visual morning / afternoon / evening grid, with weather for each day
- **Chat** — ask follow-up questions, refine your plan, or start a conversation about any destination. The chat remembers context and can re-run the full planning pipeline on request

---

## Try it now

The app is live and free to use:

**[https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app](https://travel-planner-frontend-2hrxgxqboa-ew.a.run.app)**

Log in with the credentials you were given, or contact the admin to create an account.

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
| [API Reference](docs/API-Reference.md) | All REST endpoints |
| [Setup Guide](docs/Setup-and-Installation.md) | Local dev setup |
| [Configuration](docs/Configuration.md) | All environment variables |
| [Deployment](DEPLOYMENT.md) | GCP Cloud Run deployment |

---

## Built with

- **AI** — [Anthropic Claude](https://anthropic.com) via the Agent SDK, 15 specialist agents
- **Backend** — Python, FastAPI, SQLite
- **Frontend** — React, Vite, Tailwind CSS
- **Infrastructure** — Google Cloud Run, Terraform, GitHub Actions

---

## License

MIT
