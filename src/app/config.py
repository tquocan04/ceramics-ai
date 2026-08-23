"""Application settings, loaded from environment and `.env` (plan §23).

`pydantic-settings` reads `.env` through `python-dotenv`, so a single
`Settings` object is the only place configuration enters the process. Nothing
else in the codebase may call `os.environ` directly.

Every tunable business constant lives here too (plan §13): the estimator
formulas are configuration, not code, so the workshop can recalibrate them
without a deploy.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Service ──────────────────────────────────────────────────────────
    app_name: str = "ceramics-ai-service"
    environment: Literal["local", "dev", "prod"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False
    cors_allow_origins: str = "*"

    #: When unset, the X-Internal-API-Key check is skipped so local dev stays
    #: frictionless. Setting it enforces the header on every /v1 route (§34).
    internal_api_key: SecretStr | None = None

    # ── LLM provider (§23) ───────────────────────────────────────────────
    #: Only "openai-compatible" is implemented. Any OpenAI-shaped endpoint
    #: (OpenRouter, Groq, Ollama, OpenAI itself) works via ai_base_url.
    ai_provider: Literal["openai-compatible", "fake"] = "openai-compatible"
    ai_model: str = "openai/gpt-4o-mini"
    ai_api_key: SecretStr | None = None
    ai_base_url: str = "https://openrouter.ai/api/v1"
    ai_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    ai_max_tokens: int = Field(default=2048, gt=0)

    #: Per-attempt provider timeout. The outer budget below always wins.
    ai_timeout_seconds: float = Field(default=30.0, gt=0)
    #: Whole-request ceiling, retries included (§30).
    ai_request_budget_seconds: float = Field(default=35.0, gt=0)
    #: Retries *after* the first attempt, so 2 means up to 3 calls (§29).
    ai_max_retries: int = Field(default=2, ge=0, le=5)

    max_description_chars: int = Field(default=4000, gt=0)

    # ── Estimation constants (§13) ───────────────────────────────────────
    # Ported verbatim from frontend/lib/mock/ai.ts so the numbers the review
    # UI was built against do not shift underneath it.
    clay_kg_per_unit: float = 0.9
    clay_reference_height_cm: float = 35.0
    default_height_cm: float = 30.0
    glaze_clay_ratio: float = 15.0
    firing_base_hours: float = 8.0
    firing_temp_baseline_c: float = 1200.0
    firing_degrees_per_hour: float = 40.0

    # ── Semantic validation bounds (§15) ─────────────────────────────────
    firing_temp_min_c: int = 600
    firing_temp_max_c: int = 1450

    @field_validator("ai_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @field_validator("ai_api_key", "internal_api_key", mode="before")
    @classmethod
    def _blank_secret_is_absent(cls, v: object) -> object:
        """Treat `KEY=` in `.env` as unset.

        Without this, an empty line parses to `SecretStr('')` rather than
        `None`, and every `is None` check downstream reads it as "configured".
        `.env.example` tells you to leave `INTERNAL_API_KEY` empty for local
        development -- doing so would otherwise enforce auth against an empty
        key no client can send, locking you out of your own service.
        """
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def _check_coherent(self) -> Settings:
        if self.ai_provider == "openai-compatible" and self.ai_api_key is None:
            raise ValueError(
                "AI_API_KEY is required when AI_PROVIDER=openai-compatible. "
                "Copy .env.example to .env and fill it in, or set AI_PROVIDER=fake."
            )
        if self.ai_request_budget_seconds < self.ai_timeout_seconds:
            raise ValueError(
                "AI_REQUEST_BUDGET_SECONDS must be >= AI_TIMEOUT_SECONDS, otherwise "
                "the outer budget would cancel the very first attempt."
            )
        if self.firing_temp_min_c >= self.firing_temp_max_c:
            raise ValueError("FIRING_TEMP_MIN_C must be < FIRING_TEMP_MAX_C")
        return self

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Process-wide singleton. Cached so `.env` is read exactly once."""
    return Settings()
