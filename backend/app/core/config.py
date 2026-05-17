from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# This file is at backend/app/core/config.py
# Project root is 3 levels up: backend/app/core -> backend/app -> backend -> project_root
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    agents_dir: str = str(_PROJECT_ROOT / ".agents")
    cache_ttl_seconds: int = 1800
    cache_maxsize: int = 500

    # Security
    jwt_secret_key: str = ""
    cors_origins: list[str] = ["http://localhost:5174", "http://localhost:5173"]

    # Storage
    data_dir: str = str(_PROJECT_ROOT / "backend" / "data")
    backup_bucket: str = ""  # GCS bucket name; empty = backup disabled

    # Seeded admin account (used only on first startup to create the admin user)
    admin_username: str = "admin"
    admin_password: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
