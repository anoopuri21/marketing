"""Application configuration (loaded from environment / .env)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", BASE_DIR.parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- App -------------------------------------------------------------
    app_name: str = "RankPilot"
    environment: Literal["development", "production", "test"] = "development"
    secret_key: str = "change-me-in-production-please"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days
    public_base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = "*"  # comma-separated list of allowed origins, or *

    # --- Database --------------------------------------------------------
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'app.db'}"

    # --- Crawler / audit -------------------------------------------------
    crawl_max_pages: int = 25
    crawl_timeout_seconds: float = 15.0
    crawl_concurrency: int = 5
    user_agent: str = "Mozilla/5.0 (compatible; RankPilotBot/0.1; +https://rankpilot.local/bot)"

    # --- AI (pluggable) --------------------------------------------------
    ai_provider: Literal["auto", "openai", "anthropic", "none"] = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_base_url: str = "https://api.openai.com/v1"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-haiku-latest"

    # --- SERP / rank tracking -------------------------------------------
    serp_provider: Literal["auto", "serpapi", "none"] = "auto"
    serpapi_key: str = ""

    # --- Email -----------------------------------------------------------
    email_backend: Literal["auto", "smtp", "file", "console"] = "auto"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "RankPilot Reports <reports@rankpilot.local>"
    smtp_use_tls: bool = True  # STARTTLS
    smtp_use_ssl: bool = False  # implicit TLS (port 465)
    outbox_dir: str = str(BASE_DIR / "data" / "outbox")

    # --- Scheduler -------------------------------------------------------
    scheduler_enabled: bool = True
    scheduler_tick_seconds: int = 60
    auto_audit_interval_days: int = 7

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()] or ["*"]

    # Convenience -----------------------------------------------------------
    @property
    def resolved_ai_provider(self) -> str:
        if self.ai_provider == "auto":
            if self.openai_api_key:
                return "openai"
            if self.anthropic_api_key:
                return "anthropic"
            return "none"
        return self.ai_provider

    @property
    def resolved_serp_provider(self) -> str:
        if self.serp_provider == "auto":
            return "serpapi" if self.serpapi_key else "none"
        return self.serp_provider

    @property
    def resolved_email_backend(self) -> str:
        if self.email_backend == "auto":
            return "smtp" if self.smtp_host else "file"
        return self.email_backend


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    Path(s.outbox_dir).mkdir(parents=True, exist_ok=True)
    if s.database_url.startswith("sqlite"):
        (BASE_DIR / "data").mkdir(parents=True, exist_ok=True)
    return s


settings = get_settings()
