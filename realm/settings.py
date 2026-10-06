"""Runtime settings loaded from environment variables (prefix REALM_)."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-level settings; game balance lives in realm/config/*.yaml."""

    model_config = SettingsConfigDict(env_prefix="REALM_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://realm:realm@localhost:5432/realm"


def get_settings() -> Settings:
    """Return settings read from the current environment."""
    return Settings()
