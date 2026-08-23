"""Translate provider-specific failures into this service's taxonomy (§28).

Isolating the mapping here is what keeps `pydantic-ai` an implementation
detail: swapping providers touches this file and `client.py`, nothing else.
"""

from __future__ import annotations

import httpx
from pydantic import ValidationError
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
    SchemaValidationFailed,
)


def _root_validation_error(exc: BaseException) -> ValidationError | None:
    """Walk the cause chain for the Pydantic error underneath.

    pydantic-ai raises `UnexpectedModelBehavior ... from error`, so the
    original `ValidationError` survives and can be inspected.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ValidationError):
            return current
        current = current.__cause__ or current.__context__
    return None


def _provider_message(exc: ModelHTTPError) -> str:
    """Pull the human-readable reason out of a provider error body."""
    body = exc.body
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
            if isinstance(value, dict):
                nested = value.get("message")
                if isinstance(nested, str) and nested:
                    return nested
    if isinstance(body, str) and body:
        return body[:300]
    return ""


def _is_json_syntax_error(error: ValidationError) -> bool:
    """True when the payload could not be parsed at all, vs. parsed-but-wrong."""
    return any(e["type"].startswith("json_") for e in error.errors())


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
        # Carry the provider's own words. Dropping them leaves "HTTP 400" and
        # nothing else, when the body said exactly what was wrong -- e.g.
        # "Reasoning is mandatory for this endpoint and cannot be disabled."
        detail = _provider_message(exc)
        suffix = f" {detail}" if detail else ""

        if status == 429:
            return ProviderRateLimited(f"Provider rate-limited {model}.{suffix}")
        if status in (408, 504):
            return ProviderTimeout(f"Provider returned {status} for {model}.{suffix}")
        if status >= 500:
            return ProviderUnavailable(
                f"Provider returned {status} for {model}.{suffix}"
            )
        # 4xx other than 429 is our bug (bad key, bad model id) - do not retry.
        return ProviderError(
            ErrorCode.AI_PROVIDER_ERROR,
            f"Provider rejected the request for {model} with HTTP {status}.{suffix}",
            retryable=False,
            details={"status_code": status, "provider_message": detail},
        )

    if isinstance(exc, UnexpectedModelBehavior):
        # The model replied but not in a usable shape (§6.5). Split the two
        # cases: unparseable text is the model's formatting failing (502),
        # while well-formed JSON that breaks the schema is our prompt or
        # schema failing (422). Without this split AI_SCHEMA_VALIDATION_FAILED
        # is documented in the README but unreachable in production.
        cause = _root_validation_error(exc)
        if cause is not None and not _is_json_syntax_error(cause):
            return SchemaValidationFailed(
                str(exc),
                details={
                    "errors": [
                        {"loc": ".".join(map(str, e["loc"])), "type": e["type"]}
                        for e in cause.errors()[:5]
                    ]
                },
            )
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
