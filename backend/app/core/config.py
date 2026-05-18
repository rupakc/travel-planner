from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# This file lives at backend/app/core/config.py.
# In the Docker container WORKDIR /app corresponds to the backend/ directory,
# so going 4 levels up reaches "/" (container root), not the project root.
# All production paths are therefore set explicitly via env vars (AGENTS_DIR,
# DATA_DIR, BACKUP_BUCKET) injected by Cloud Run / Terraform.
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

    # Third-party API keys
    serpapi_key: str = ""  # SerpAPI key; empty = AI agent fallback for flights

    # Seeded admin account (used only on first startup to create the admin user)
    admin_username: str = "admin"
    admin_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
