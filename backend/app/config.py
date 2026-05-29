"""Environment-driven application settings.

All configuration comes from the environment (or a local ``.env`` file in dev).
Nothing here imports the DB or models, so it is safe to import from anywhere
(app, Alembic env, scripts, tests).
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- App ---
    app_env: str = Field(default="dev", description="dev | test | prod")
    log_level: str = Field(default="INFO")

    # --- Database ---
    # The application MUST use Neon's *pooled* (-pooler) endpoint. asyncpg + PgBouncer
    # requires prepared-statement caching to be disabled; db.py handles that.
    database_url: str = Field(
        default="postgresql+asyncpg://user:pass@localhost:5432/tuition",
        description="Async (asyncpg) URL for the app. Use Neon's pooled -pooler endpoint.",
    )
    # Alembic may run against a *direct* (non-pooled) endpoint. Falls back to database_url.
    alembic_database_url: str | None = Field(
        default=None,
        description="Optional direct (non-pooled) URL for migrations. Defaults to database_url.",
    )

    # --- Telegram bot (used from Phase 3) ---
    bot_token: str | None = Field(default=None)
    telegram_webhook_secret: str | None = Field(default=None)
    telegram_webhook_url: str | None = Field(default=None)

    # --- Solver (defaults; per-run weights live in SolverInput) ---
    solver_time_limit_seconds: float = Field(default=10.0)
    solver_random_seed: int = Field(default=42)
    solver_num_workers: int = Field(
        default=8, description="Use 1 in tests for deterministic CP-SAT output.")

    # --- Scheduling fallback timezone (authoritative tz lives in institution_settings) ---
    default_timezone: str = Field(default="Asia/Kolkata")

    @property
    def migration_url(self) -> str:
        """URL Alembic should connect with (direct endpoint if provided)."""
        return self.alembic_database_url or self.database_url


@lru_cache
def get_settings() -> Settings:
    """Cached singleton so the env is parsed once per process."""
    return Settings()


settings = get_settings()
