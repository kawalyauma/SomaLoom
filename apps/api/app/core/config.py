from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://somaloom:development@localhost/somaloom"
    redis_url: str = "redis://localhost:6379/0"
    allowed_origins: str = "http://localhost:3000"
    session_hours: int = 12
    storage_root: str = "/data/resources"
    ai_provider: str = "disabled"

    @model_validator(mode="after")
    def production(self):
        if self.app_env not in {"development", "test", "production"}:
            raise ValueError("Invalid APP_ENV")
        if self.session_hours < 1 or self.session_hours > 168:
            raise ValueError("Session lifetime must be 1..168 hours")
        if self.app_env == "production":
            if not self.database_url.startswith("postgresql+psycopg://"):
                raise ValueError("Production requires PostgreSQL")
            if not all(x.startswith("https://") for x in self.origins):
                raise ValueError("Production origins must use HTTPS")
        return self

    @property
    def origins(self):
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]


@lru_cache
def get_settings():
    return Settings()
