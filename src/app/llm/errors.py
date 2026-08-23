"""Translate provider-specific failures into this service's taxonomy (§28).

Isolating the mapping here is what keeps `pydantic-ai` an implementation
detail: swapping providers touches this file and `client.py`, nothing else.
"""

from __future__ import annotations

import httpx
from pydantic_ai.exceptions import (
    ModelAPIError,
    ModelHTTPError,
    UnexpectedModelBehavior,
    UserError,
)

from app.common.enums import ErrorCode
from app.exceptions import (
    InvalidModelOutput,
    ProviderError,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)


def map_provider_exception(exc: BaseException, *, model: str) -> ProviderError:
    """Best-effort classification. Anything unrecognised is non-retryable."""
    if isinstance(exc, ProviderError):
        return exc

    if isinstance(exc, TimeoutError | httpx.TimeoutException):
        return ProviderTimeout(f"Provider {model} timed out.")

    if isinstance(exc, httpx.ConnectError | httpx.NetworkError):
        return ProviderUnavailable(f"Cannot reach provider for {model}: {exc}")

    if isinstance(exc, ModelHTTPError):
        status = exc.status_code
        if status == 429:
            return ProviderRateLimited(f"Provider rate-limited {model}.")
        if status in (408, 504):
            return ProviderTimeout(f"Provider returned {status} for {model}.")
        if status >= 500:
            return ProviderUnavailable(f"Provider returned {status} for {model}.")
        # 4xx other than 429 is our bug (bad key, bad model id) - do not retry.
        return ProviderError(
            ErrorCode.AI_PROVIDER_ERROR,
            f"Provider rejected the request for {model} with HTTP {status}.",
            retryable=False,
            details={"status_code": status},
        )

    if isinstance(exc, UnexpectedModelBehavior):
        # The model replied but not in a usable shape (§6.5).
        return InvalidModelOutput(str(exc), raw=getattr(exc, "body", None))

    if isinstance(exc, ModelAPIError):
        return ProviderUnavailable(str(exc))

    if isinstance(exc, UserError):
        # Misconfiguration on our side, e.g. an unknown model name.
        return ProviderError(
            ErrorCode.AI_PROVIDER_ERROR, str(exc), retryable=False
        )

    return ProviderError(
        ErrorCode.AI_PROVIDER_ERROR,
        f"Unexpected provider failure: {exc}",
        retryable=False,
    )
