from pathlib import Path
from typing import Literal

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
    # LLM provider for every model call (core/llm.py): "gemini" = Gemini on
    # Vertex AI with Application Default Credentials (no API key);
    # "anthropic" = Claude via ANTHROPIC_API_KEY (local dev / rollback);
    # "auto" = gemini when GCP_PROJECT is set (or, without an Anthropic key,
    # when ADC resolves a project), otherwise anthropic
    llm_provider: str = "auto"
    anthropic_api_key: str = ""
    # Vertex AI project (empty = GOOGLE_CLOUD_PROJECT / the ADC project) and
    # location ("global" routes to any region with capacity)
    gcp_project: str = ""
    gcp_location: str = "global"
    # Specialists, routing, extraction, itineraries → the cheap model;
    # conversational chat answers and narrative → the stronger one
    gemini_model_agent: str = "gemini-3.5-flash-lite"
    gemini_model_chat: str = "gemini-3.8-flash"
    # Thinking level (minimal | low | medium | high); 3.8 Flash rejects minimal
    gemini_thinking_agent: str = "minimal"
    gemini_thinking_chat: str = "low"
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
    # Max concurrent LLM calls across all specialist agents — a
    # 12-agent burst with large outputs trips org rate limits and every
    # section fails at once
    agent_max_concurrency: int = 6
    # /search and /chat: ": keepalive" after this many quiet seconds
    sse_keepalive_seconds: float = 15.0
    serper_key: str = (
        ""  # Serper Google Search API key; enables Tier 2 activity URL resolution
    )

    # Product telemetry (POST /api/telemetry): raw events kept in
    # $DATA_DIR/telemetry.db for this many days; TELEMETRY_ENABLED=false makes
    # the endpoint 404 (clients then switch themselves off).
    telemetry_enabled: bool = True
    telemetry_retention_days: int = 90
    # Global disk guard (all callers together): past either cap /api/telemetry
    # still answers 204 but drops the batch. Size = telemetry.db + its WAL;
    # the daily cap counts rows stored per UTC day.
    telemetry_max_db_mb: int = 1024
    telemetry_max_events_per_day: int = 200000
    # Absolute origin handed to clients by GET /api/config (share links); empty =
    # the request's own base URL
    public_base_url: str = ""

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
    rate_limit_share_public: int = 120  # public share page, JSON and card (per IP)
    rate_limit_share_manage: int = 30  # /shares create, list, revoke (per user)
    rate_limit_play: int = 60  # /play/* (per user)
    rate_limit_telemetry: int = 120  # POST /telemetry (batches, not events)
    # Phase 5 (Social + Play), per user: writes, reads, Play, admin moderation
    rate_limit_social_write: int = 30
    rate_limit_social_read: int = 120
    rate_limit_play: int = 60
    rate_limit_admin: int = 120
    # /auth/login: attempts per client IP; failed attempts per (username, IP),
    # so others can't lock a user out; and a high per-username ceiling across
    # all IPs as a backstop against distributed guessing
    rate_limit_login: int = 10
    rate_limit_login_failures: int = 10
    rate_limit_login_failures_global: int = 200
    # Phase 1 accounts: email-bound buckets and the new auth/account routes
    rate_limit_auth_email: int = 10
    rate_limit_email_address: int = 3
    rate_limit_signup: int = 5
    rate_limit_oauth: int = 30
    rate_limit_refresh: int = 60
    rate_limit_account: int = 30
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

    # --- Phase 1: accounts, OAuth, daily AI quota, game ---
    signup_mode: Literal["open", "invite"] = "open"
    # Native (password) sign-up is off until the operator opts in: setting
    # SMTP for fare alerts must not open public registration by itself.
    signup_enabled: bool = False
    email_log_links: bool = False  # dev: log verification/reset links
    account_token_ttl_minutes: int = 30
    pending_purge_days: int = 7
    refresh_token_days: int = 60
    refresh_family_max_days: int = 365
    mobile_access_token_minutes: int = 60
    google_client_id: str = ""
    google_client_secret: str = ""
    google_native_client_ids: list[str] = []
    github_client_id: str = ""
    github_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    facebook_graph_version: str = "v24.0"
    facebook_email_trusted: bool = False
    apple_services_id: str = ""
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key: str = ""
    apple_native_client_ids: list[str] = []
    # "<base>/auth/callback" is always allowed in addition
    oauth_mobile_redirects: list[str] = ["voyager://auth/callback"]
    # Daily AI quota per signed-in user (0 = unlimited)
    ai_daily_quota_enabled: bool = True
    ai_daily_quota_search: int = 20
    ai_daily_quota_chat: int = 100
    ai_daily_quota_compare: int = 40
    ai_daily_quota_discover: int = 20
    ai_daily_quota_light_ai: int = 200
    ai_daily_quota_import: int = 20
    game_enabled: bool = True
    # Play (Phase 5): quizzes, head-to-head, boards. Also needs game_enabled.
    play_enabled: bool = False
    journey_ui_enabled: bool = True
    # Price alerts 2.0 (Phase 3): the pipeline, delivery and digest loops
    price_alerts_v2_enabled: bool = True
    alert_digest_hour_local: int = 9
    alert_flush_interval_s: int = 60
    alert_advice_ttl_hours: int = 24
    offline_pack_enabled: bool = True
    # Notifications 2.0 (Phase 6): category checks, trip pushes, platform routing.
    # The settings routes always exist; off = the Phase 3 behaviour unchanged.
    notifications_v2_enabled: bool = True
    apns_team_id: str = ""
    apns_key_id: str = ""
    apns_key_p8: str = ""
    apns_key_file: str = ""
    apns_bundle_id: str = "io.github.rupakc.travelplanner"
    apns_sandbox: bool = False
    # Phase 5: profiles, ideas feed, moderation (SOCIAL_ENABLED) and quizzes,
    # head-to-head, boards, challenges (PLAY_ENABLED, also needs GAME_ENABLED).
    # Off = routes 404 and features.social / features.play are 0.
    social_enabled: bool = False
    play_enabled: bool = False
    # Sharing 2.0 (Phase 4): /api/shares, card and OG page
    sharing_v2_enabled: bool = True
    ready_window_days: int = 14
    trip_max_expenses: int = 2000
    trip_max_journal: int = 500
    trip_max_places: int = 1000
    trip_snapshot_max_bytes: int = 262144
    game_rules_path: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
