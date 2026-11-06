from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at backend/app/core/config.py.
# In the Docker container WORKDIR /app corresponds to the backend/ directory,
# so going 4 levels up reaches "/" (container root), not the project root.
# All production paths are therefore set explicitly via env vars (AGENTS_DIR,
# DATA_DIR, BACKUP_BUCKET) injected by the deployment (deploy/gcp/app.env).
_BACKEND_ROOT = Path(
    __file__
).parent.parent.parent  # /app in container, backend/ locally
_PROJECT_ROOT = _BACKEND_ROOT.parent  # / in container, project root locally


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    # AGENTS_DIR env var overrides this; falls back to project-root .agents/ for local dev
    agents_dir: str = str(_PROJECT_ROOT / ".agents")
    cache_ttl_seconds: int = 1800
    cache_maxsize: int = 500

    # Security
    jwt_secret_key: str = ""
    cors_origins: list[str] = ["http://localhost:5174", "http://localhost:5173"]

    # Storage — DATA_DIR env var overrides in production
    data_dir: str = str(_BACKEND_ROOT / "data")
    backup_bucket: str = ""  # GCS bucket name; empty = backup disabled
    # "cloudrun" (default, legacy): restore at every start, periodic merge-safe
    # uploads. "vm": the persistent disk is authoritative: restore only when
    # the DB is missing (DATA_DIR must hold the .voyager-data-disk marker),
    # never merge, upload the user tables when they changed (app/db/vm_backup.py)
    backup_mode: str = "cloudrun"
    backup_interval_seconds: int = 300  # vm mode cadence
    backup_export_dir: str = ""  # vm mode scratch dir (a tmpfs); "" = system temp

    # Third-party API keys
    serpapi_key: str = ""  # SerpAPI key; empty = AI agent fallback for flights
    # Max concurrent Anthropic API calls across all specialist agents — a
    # 12-agent burst with large outputs trips org rate limits and every
    # section fails at once
    agent_max_concurrency: int = 6
    # /search and /chat: ": keepalive" after this many quiet seconds
    sse_keepalive_seconds: float = 15.0
    serper_key: str = (
        ""  # Serper Google Search API key; enables Tier 2 activity URL resolution
    )

    # Rate limits on AI endpoints: max requests per caller (signed-in user, or
    # client IP when anonymous) per rolling window. RATE_LIMIT_ENABLED=false
    # turns them off.
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 600
    rate_limit_search: int = 10  # /search, /search/sync
    rate_limit_chat: int = 30  # /chat
    rate_limit_compare: int = 30  # /compare/destination
    rate_limit_discover: int = 10  # /discover
    rate_limit_light_ai: int = 60  # single-agent routes, /stress-test, /*/filtered
    rate_limit_import: int = 20  # /import/extract (plan from a link)
    # /auth/login: attempts per client IP, and failed attempts per username
    rate_limit_login: int = 10
    rate_limit_login_failures: int = 20
    # false = every AI route requires sign-in (production); true keeps the
    # anonymous /search, /discover and single-agent routes (local dev)
    allow_anonymous_ai: bool = True

    # Fare watch: background re-checks of watched fares (needs SERPAPI_KEY).
    # One check = 1 SerpAPI call (exact dates) or up to 7 (±3 nearby dates);
    # cached fares cost nothing. Run one backend worker: see Deployment.md.
    fare_watch_enabled: bool = True
    fare_watch_tick_seconds: int = 300  # how often the scheduler looks for due checks
    fare_watch_interval_hours: float = 12  # between checks of one watch (±10 %)
    fare_watch_daily_call_budget: int = 200  # SerpAPI calls/day (UTC) for watches
    fare_watch_max_active_per_user: int = 10
    # One user's daily share of that budget (all their watches together)
    fare_watch_user_daily_share: float = 0.3

    # Email alerts (optional): sent only when SMTP_HOST is set
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_starttls: bool = True
    # Push alerts to the Android app (optional): path to a Firebase service-account
    # JSON key; empty = push disabled (alerts stay in-app / email only)
    fcm_service_account_file: str = ""
    # ...or, with no key file, Application Default Credentials (the VM's service
    # account; needs FCM send rights). The project comes from FCM_PROJECT_ID,
    # else GOOGLE_CLOUD_PROJECT (the entrypoint sets it from the metadata server)
    fcm_use_adc: bool = False
    fcm_project_id: str = ""
    # Public URL of the frontend, for links in emails
    app_base_url: str = "http://localhost:5174"

    # Seeded admin account (used only on first startup to create the admin user)
    admin_username: str = "admin"
    admin_password: str = ""
    admin_email: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
