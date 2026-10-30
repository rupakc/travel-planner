# Contributing

## Setup

```bash
# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
# create backend/.env with ANTHROPIC_API_KEY, JWT_SECRET_KEY, ADMIN_PASSWORD

# Frontend
cd frontend
npm install

# Optional: pre-commit hooks
make install-hooks
```

Run both servers with `./start.sh` (backend 8001, frontend 5174) and stop them with `./stop.sh`. Details: [Setup and Installation](Setup-and-Installation.md).

## Workflow

1. Branch off `main`.
2. Make the change with tests: `backend/tests/` for Python, `*.test.js(x)` next to the code for the frontend.
3. Run the checks locally with `make ci` from the repo root: lint (ruff and ESLint), the security scans and both test suites, mirroring CI. See [Testing and CI](Testing-and-CI.md).
4. Push and open a pull request to `main`. CI (`ci.yml`) runs lint, security audits, both test suites with the 70% backend coverage gate, and an image build with a Trivy scan.
5. Merging to `main` publishes the docs site (`docs.yml`). It does **not** deploy the app: `deploy.yml` is manual-only and decommissioned (see [Deployment](Deployment.md)).

Merged PRs are listed in the [Changelog](Changelog.md).

## Code style

- **Backend**: ruff for lint and format (`ruff check`, `ruff format`), Python 3.12, Pydantic v2 models for request and response shapes.
- **Frontend**: ESLint with the project config; import lucide icons that shadow globals (Map, Image, History…) under an alias. Tailwind utility classes; keep pure logic in `src/utils/` where it can be unit-tested.
- Comment only where the reason is not obvious from the code.
- No error handling for cases that cannot happen, and no abstractions beyond what the task needs.

## Conventions

- **Agent prompts are config.** Change agent behaviour in `.agents/<name>.md` (name and description frontmatter plus the prompt). The Python class builds the user prompt and parses the JSON. See [Agent System](Agent-System.md#adding-an-agent) for adding an agent.
- **Agents return JSON**, parsed by `BaseAgent._parse_json`.
- **Parallel first.** Independent agents run concurrently; only the itinerary and stress test depend on other results.
- **Static first.** Visa, SIM, tips, getting around, forex and the emergency card have static tables; an AI failure must never replace valid static data with an error.
- **Verification from evidence only.** `services/verification.py` must stay pure (no network or LLM calls) and must never put an `error` key in the verification object.
- **Place data is generated.** Do not hand-edit `airports.csv`, `places.csv.gz`, `admin1.csv` or `countries.csv`; regenerate them (see [Place and Airport Data](Place-and-Airport-Data.md#regenerating-the-data)). `hints.json` is hand-curated; add a golden-set case for every hint you add.
- **Prompts pair a city with its country** ("Lisbon, Portugal"), so agents do not guess the wrong namesake.

## Licence

The project is released under the MIT License (`LICENSE`). Place data contains data from GeoNames (geonames.org), CC BY 4.0, and must keep that attribution; OurAirports data is public domain.
