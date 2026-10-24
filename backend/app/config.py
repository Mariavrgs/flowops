from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables (and .env in development)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://flowops:change-me-locally@localhost:5432/flowops"

    session_cookie_name: str = "flowops_session"
    session_ttl_hours: int = 12
    # Must be true behind HTTPS. False by default so plain-HTTP local development works.
    cookie_secure: bool = False


settings = Settings()
