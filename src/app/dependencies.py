"""FastAPI dependency wiring.

The provider is constructed once and cached: building an HTTP client per
request would leak connections under load.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header

from app.common.enums import ErrorCode
from app.config import Settings, get_settings
from app.exceptions import AIServiceError
from app.features.order_extraction.service import OrderExtractionService
from app.llm.client import FakeProvider, PydanticAIProvider
from app.llm.provider import LLMProvider

__all__ = ["get_extraction_service", "get_provider", "require_internal_api_key"]


@lru_cache(maxsize=1)
def _build_provider() -> LLMProvider:
    """Construct the provider once per process.

    Takes no argument on purpose. `Settings` is a Pydantic model and therefore
    unhashable, so caching on it raises `TypeError` on every call; `get_settings`
    is already a process-wide singleton, so reading it here is equivalent and
    actually cacheable.
    """
    settings = get_settings()
    if settings.ai_provider == "fake":
        # Only reachable when AI_PROVIDER=fake is set deliberately; the success
        # path needs a responder, so this exists to let /health and the error
        # paths run with no API key present.
        return FakeProvider(name="fake", model=settings.ai_model)
    return PydanticAIProvider(settings)


def get_provider() -> LLMProvider:
    return _build_provider()


def get_extraction_service(
    provider: Annotated[LLMProvider, Depends(get_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OrderExtractionService:
    return OrderExtractionService(provider, settings)


def require_internal_api_key(
    settings: Annotated[Settings, Depends(get_settings)],
    x_internal_api_key: Annotated[str | None, Header()] = None,
) -> None:
    """Backend-to-service authentication (plan §34).

    Skipped entirely when INTERNAL_API_KEY is unset so local development needs
    no header. Comparison is constant-time.
    """
    if settings.internal_api_key is None:
        return

    expected = settings.internal_api_key.get_secret_value()
    if x_internal_api_key is None or not secrets.compare_digest(
        x_internal_api_key, expected
    ):
        raise AIServiceError(
            ErrorCode.UNAUTHORIZED, "Thiếu hoặc sai X-Internal-API-Key."
        )
