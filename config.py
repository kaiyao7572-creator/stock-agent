"""Environment-driven application configuration."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    cerebras_api_key: str = ""
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    alpha_vantage_api_key: str = ""
    discord_webhook: str = ""
    database_url: str = "sqlite+aiosqlite:///./stock_agent.db"

    app_api_key: str = ""
    allowed_origins: str = ""
    daily_scan_cron: str = "0 23 * * *"
    enable_scheduler: bool = False
    refresh_rate_limit_per_minute: int = 5
    webhook_rate_limit_per_minute: int = 30
    top_n_stocks: int = 10
    environment: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip():
            return [
                origin.strip()
                for origin in self.allowed_origins.split(",")
                if origin.strip()
            ]
        if self.is_production:
            return []
        return [
            "http://localhost:8000",
            "http://localhost:3000",
            "http://127.0.0.1:8000",
            "http://127.0.0.1:3000",
        ]

    @model_validator(mode="after")
    def validate_production(self):
        if self.is_production:
            missing = []
            if not self.app_api_key:
                missing.append("APP_API_KEY")
            if not self.cerebras_api_key:
                missing.append("CEREBRAS_API_KEY")
            if not any(
                [
                    self.finnhub_api_key,
                    self.polygon_api_key,
                    self.alpha_vantage_api_key,
                ]
            ):
                missing.append("FINNHUB_API_KEY, POLYGON_API_KEY, or ALPHA_VANTAGE_API_KEY")
            if not self.cors_origins:
                missing.append("ALLOWED_ORIGINS")
            if missing:
                raise ValueError(
                    "Missing required production settings: " + ", ".join(missing)
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
