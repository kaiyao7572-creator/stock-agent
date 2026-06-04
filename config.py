"""
Central configuration — all settings loaded from environment variables.
Never hard-code secrets. Copy .env.example to .env and fill in values.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── AI ──────────────────────────────────────────────
    cerebras_api_key: str = ""

    # ── Market Data ─────────────────────────────────────
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    alpha_vantage_api_key: str = ""          # fallback

    # ── Notifications ────────────────────────────────────
    discord_webhook: str = ""

    # ── Database ─────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./stock_agent.db"

    # ── Runtime ──────────────────────────────────────────
    daily_scan_cron: str = "0 23 * * *"     # 11 PM local every night
    top_n_stocks: int = 10
    environment: str = "development"

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
