# Travel Planner

AI-powered travel planning. Give it your destination, dates, and interests — it returns flights, hotels, activities, visa requirements, SIM recommendations, transport options, and a day-by-day itinerary in one go. Results stream section by section in real time.

## Features

- **Multi-agent AI** — 8 specialist Claude agents run in parallel (flights, hotels, activities, visa, SIM, tips, transport, itinerary)
- **Real-time streaming** — results appear section by section via SSE, no waiting for all agents
- **My Plan** — select flights, hotels, activities and more into a named plan; save and reload anytime
- **Chat interface** — conversational trip planning that auto-triggers the agent pipeline
- **User feedback** — floating feedback widget on every page; admin can view and export
- **Multi-user auth** — admin-created accounts with forced first-login password change
- **Admin panel** — create/deactivate users, view feedback, manage the app
- **Mobile responsive** — works on all screen sizes
- **Production-ready** — Cloud Run, Terraform IaC, GitHub Actions CI/CD, structured logging, Cloud Monitoring

## Architecture

```
Frontend (React + Vite)
        │  SSE stream  │  REST API
        ▼              ▼
  Backend (FastAPI) ──► Multi-Agent Orchestrator
                               │
              ┌────────────────┼────────────────┐
              │                │                │
     Phase 0 (instant)  Phase 1 (parallel)  Phase 2 (sequential)
     Static lookups      7 specialist agents  Itinerary synthesis
```

See [docs/architecture.md](docs/architecture.md) for full details.

## Quick Start

```bash
# Clone
git clone https://github.com/your-org/travel-planner && cd travel-planner

# Set up environment
cp backend/.env.example backend/.env
# Edit backend/.env — set ANTHROPIC_API_KEY and ADMIN_PASSWORD at minimum

# Start both servers
./start.sh

# Open
open http://localhost:5174
```

## Running with Docker

```bash
cp backend/.env.example .env  # set ANTHROPIC_API_KEY, ADMIN_PASSWORD
docker compose up
open http://localhost:8080
```

## API

| Endpoint | Description |
|---|---|
| `POST /api/auth/login` | JWT login |
| `GET  /api/auth/me` | Current user |
| `POST /api/auth/change-password` | Update password |
| `GET  /api/admin/users` | List users (admin) |
| `POST /api/admin/users` | Create user (admin) |
| `POST /api/search` | SSE streaming trip search |
| `POST /api/chat` | SSE streaming chat |
| `GET/PUT /api/preferences` | User preferences |
| `GET/POST /api/plans` | Saved plans |
| `POST /api/feedback` | Submit feedback |
| `GET  /api/admin/feedback` | View feedback (admin) |
| `POST /api/analytics/events` | Track frontend events |
| `GET  /health` | Health check |

Full OpenAPI docs available at `/docs` when the backend is running.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Required. Your Anthropic API key |
| `ADMIN_PASSWORD` | — | Seeds the initial `admin` account on startup |
| `JWT_SECRET_KEY` | `change-me` | JWT signing secret — change in production |
| `DATA_DIR` | `backend/data` | Where SQLite databases are stored |
| `BACKUP_BUCKET` | (empty) | GCS bucket for SQLite backup; empty = disabled |
| `CORS_ORIGINS` | `http://localhost:5174` | Allowed CORS origins (comma-separated list) |
| `LOG_FORMAT` | `json` | `json` for Cloud Logging, `text` for local dev |

## Running Tests

```bash
# Backend (from backend/)
pip install -r requirements-dev.txt
pytest --cov=app --cov-fail-under=70

# Frontend unit tests (from frontend/)
npx vitest run --coverage

# E2E tests (requires docker compose up)
docker compose up -d
npx playwright test
docker compose down
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for step-by-step GCP deployment.

## Developer Docs

Auto-generated from code, published to GitHub Pages on every push to `main`:
`https://<your-org>.github.io/travel-planner`

## Contributing

See [docs/contributing.md](docs/contributing.md).

## License

MIT
