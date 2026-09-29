"""Typed configuration loaded from the environment / .env (spec §7, §9).

Secrets are NEVER hardcoded here. They are read from environment variables
only. This module exposes non-secret, typed settings and convenience access
to secret names without ever printing their values.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load .env into the process environment so secrets read via os.getenv()
# (FINNHUB_API_KEY, TELEGRAM_*) are visible too — not just the typed settings
# below. Does not override variables already set in the real environment.
load_dotenv(PROJECT_ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TRADEER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage ---
    db_path: str = Field(default="data/tradeer.db")

    # --- Risk thresholds (Phase 1), all fractions of portfolio in [0, 1] ---
    max_position_pct: float = Field(default=0.25, ge=0.0, le=1.0)
    max_sector_pct: float = Field(default=0.40, ge=0.0, le=1.0)
    max_drawdown_pct: float = Field(default=0.20, ge=0.0, le=1.0)

    # --- Information layer (Phase 2), non-secret config only ---
    # SEC EDGAR requires a descriptive User-Agent with contact info.
    sec_user_agent: str = Field(default="tradeer/0.1 (contact@example.com)")
    # How far back to pull company news, and how far ahead to watch earnings.
    news_lookback_days: int = Field(default=7, ge=1, le=90)
    earnings_lookahead_days: int = Field(default=14, ge=1, le=90)
    # Alert when an earnings date is within this many days.
    earnings_alert_days: int = Field(default=5, ge=0, le=60)

    # --- Claude analysis layer (Phase 4), non-secret config only ---
    # ANTHROPIC_API_KEY is a secret read via os.getenv(), never stored here.
    claude_model: str = Field(default="claude-opus-4-7")
    claude_max_tokens: int = Field(default=8000, ge=256, le=64000)

    @field_validator("db_path")
    @classmethod
    def _resolve_db_path(cls, v: str) -> str:
        p = Path(v)
        if not p.is_absolute():
            p = PROJECT_ROOT / p
        return str(p)

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    def ensure_data_dir(self) -> None:
        """Create the parent directory for the SQLite file if missing."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
