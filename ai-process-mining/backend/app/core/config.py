"""Settings come from environment variables only, so nothing secret lives in the repo."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env(name: str, default: str | None = None) -> str | None:
    # Treat an empty value (e.g. `ANTHROPIC_API_KEY=` in .env) the same as unset.
    value = os.environ.get(name, "").strip()
    return value or default


def _env_number(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str
    upload_dir: str
    max_upload_mb: float
    max_rows: int
    default_timezone: str  # applied to timestamps that have no UTC offset
    cors_origins: tuple[str, ...]
    log_level: str

    llm_provider: str  # "none" or "anthropic"
    llm_model: str
    anthropic_api_key: str | None
    anthropic_base_url: str
    llm_timeout_s: float
    llm_max_tokens: int
    # USD per million tokens. Only used to put a cost estimate in the ai_runs table.
    llm_price_in_per_mtok: float
    llm_price_out_per_mtok: float

    @property
    def max_upload_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider == "anthropic" and bool(self.anthropic_api_key)


def load_settings() -> Settings:
    origins = _env("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return Settings(
        database_url=_env("DATABASE_URL", "postgresql+psycopg://apm:apm@localhost:5432/apm"),
        upload_dir=_env("UPLOAD_DIR", "/tmp/apm_uploads"),
        max_upload_mb=_env_number("MAX_UPLOAD_MB", 50),
        max_rows=int(_env_number("MAX_ROWS", 1_000_000)),
        default_timezone=_env("DEFAULT_TIMEZONE", "UTC"),
        cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip()),
        log_level=_env("LOG_LEVEL", "INFO"),
        llm_provider=_env("LLM_PROVIDER", "none").lower(),
        llm_model=_env("LLM_MODEL", "claude-sonnet-5"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        anthropic_base_url=_env("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
        llm_timeout_s=_env_number("LLM_TIMEOUT_S", 90),
        llm_max_tokens=int(_env_number("LLM_MAX_TOKENS", 4000)),
        llm_price_in_per_mtok=_env_number("LLM_PRICE_IN_PER_MTOK", 0),
        llm_price_out_per_mtok=_env_number("LLM_PRICE_OUT_PER_MTOK", 0),
    )


@lru_cache
def get_settings() -> Settings:
    return load_settings()
