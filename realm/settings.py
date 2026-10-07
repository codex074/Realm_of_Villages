"""Runtime settings loaded from environment variables (prefix REALM_)."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-level settings; game balance lives in realm/config/*.yaml."""

    database_url: str = "postgresql+psycopg://realm:realm@localhost:5432/realm"
    config_dir: str = str(Path(__file__).parent / "config")
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    auth_required: bool = False  # Phase 3 multiplayer mode: login accounts, one player per account
    session_ttl_hours: int = 24 * 14
    rate_limit_per_10s: int = 60  # mutating API calls per account (or IP) per 10 seconds
    model_config = SettingsConfigDict(env_prefix="REALM_", env_file=".env", extra="ignore")


def get_settings() -> Settings:
    """Return settings read from the current environment."""
    return Settings()


settings = Settings()
