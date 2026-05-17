# Travel Planner

AI-powered travel planning application built on Anthropic's Claude.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, uvicorn |
| AI | Claude via Anthropic SDK, multi-agent orchestration |
| Frontend | React 18, Vite, Tailwind CSS 4 |
| Persistence | SQLite (backed up to GCS on Cloud Run) |
| Auth | JWT (python-jose), bcrypt |
| Infra | Cloud Run v2, Terraform, GitHub Actions |
| Observability | Cloud Monitoring, Cloud Logging (structured JSON) |

## Features

- Real-time SSE streaming of AI agent results
- 8 specialist agents (flights, hotels, activities, visa, SIM, tips, transport, itinerary)
- My Plan — select, save, and reload travel plans
- Conversational chat with auto-planning
- User feedback widget on every page
- Admin panel (user management, feedback view)
- Mobile responsive UI
- Production monitoring, alerting, and log-based analytics

## Quick links

- [Architecture](architecture.md) — how the multi-agent system works
- [Agent System](agents.md) — how to add or modify agents
- [API Reference](api.md) — endpoint documentation
- [Deployment](deployment.md) — step-by-step GCP deploy guide
