"""Retry policy and internal authentication.

Retry behaviour is easy to get backwards -- retrying a schema failure wastes
credits producing the same wrong answer -- so the distinction is asserted
directly rather than left to the integration tests.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.common.enums import ErrorCode
from app.common.retry import build_retrying
from app.config import Settings, get_settings
from app.dependencies import get_provider
from app.exceptions import (
    ProviderRateLimited,
    ProviderTimeout,
    SchemaValidationFailed,
)
from app.llm.client import FakeProvider
from tests.conftest import SAMPLE_DESCRIPTION

# ── Retry ────────────────────────────────────────────────────────────────────


async def test_transient_failure_is_retried_then_succeeds() -> None:
    attempts = 0

    async for attempt in build_retrying(max_retries=2):
        with attempt:
            attempts += 1
            if attempts < 3:
                raise ProviderTimeout("still warming up")

    assert attempts == 3


async def test_retries_are_bounded() -> None:
    attempts = 0

    with pytest.raises(ProviderRateLimited):
        async for attempt in build_retrying(max_retries=2):
            with attempt:
                attempts += 1
                raise ProviderRateLimited("always limited")

    # One initial call plus two retries.
    assert attempts == 3


async def test_schema_failure_is_not_retried() -> None:
    """Plan §29: a semantic failure will fail identically next time."""
    attempts = 0

    with pytest.raises(SchemaValidationFailed):
        async for attempt in build_retrying(max_retries=3):
            with attempt:
                attempts += 1
                raise SchemaValidationFailed("quantity must be positive")

    assert attempts == 1


async def test_no_retry_when_the_first_attempt_works() -> None:
    attempts = 0

    async for attempt in build_retrying(max_retries=2):
        with attempt:
            attempts += 1

    assert attempts == 1


# ── Configuration guards ─────────────────────────────────────────────────────


def test_missing_api_key_is_rejected_at_startup() -> None:
    """Fail on boot, not on the first customer request."""
    with pytest.raises(ValueError, match="AI_API_KEY"):
        Settings(ai_provider="openai-compatible", ai_api_key=None, _env_file=None)


def test_budget_below_attempt_timeout_is_rejected() -> None:
    with pytest.raises(ValueError, match="AI_REQUEST_BUDGET_SECONDS"):
        Settings(
            ai_provider="fake",
            ai_timeout_seconds=30,
            ai_request_budget_seconds=10,
            _env_file=None,
        )


def test_base_url_trailing_slash_is_stripped() -> None:
    settings = Settings(
        ai_provider="fake", ai_base_url="https://example.com/v1/", _env_file=None
    )
    assert settings.ai_base_url == "https://example.com/v1"


# ── Internal API key (plan §34) ──────────────────────────────────────────────


@pytest.fixture
def secured_client(monkeypatch: pytest.MonkeyPatch, sample_extraction):
    monkeypatch.setenv("AI_PROVIDER", "fake")
    monkeypatch.setenv("INTERNAL_API_KEY", "s3cret")
    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_provider] = lambda: FakeProvider(
        responder=lambda _: sample_extraction
    )
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


def test_missing_key_is_rejected(secured_client: TestClient) -> None:
    response = secured_client.post(
        "/v1/orders/extract", json={"description": SAMPLE_DESCRIPTION}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == ErrorCode.UNAUTHORIZED


def test_wrong_key_is_rejected(secured_client: TestClient) -> None:
    response = secured_client.post(
        "/v1/orders/extract",
        json={"description": SAMPLE_DESCRIPTION},
        headers={"X-Internal-API-Key": "wrong"},
    )
    assert response.status_code == 401


def test_correct_key_is_accepted(secured_client: TestClient) -> None:
    response = secured_client.post(
        "/v1/orders/extract",
        json={"description": SAMPLE_DESCRIPTION},
        headers={"X-Internal-API-Key": "s3cret"},
    )
    assert response.status_code == 200


def test_health_stays_open(secured_client: TestClient) -> None:
    """Liveness must not depend on the caller holding a key."""
    assert secured_client.get("/health").status_code == 200


# ── Console encoding (Windows) ───────────────────────────────────────────────


def test_vietnamese_logging_survives_a_cp1252_console(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A Windows console is cp1252 and cannot encode 'ấ'.

    Every description this service handles is Vietnamese, so an unguarded
    logger would raise UnicodeEncodeError and fail the request.
    """
    import io
    import sys

    from app.logging import configure_logging, get_logger

    original = sys.stdout
    sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    try:
        configure_logging(level="INFO")
        get_logger("test").info(
            "extract.start", description="Gấp: 350 đĩa gốm men nâu họa tiết chim hạc"
        )
    finally:
        sys.stdout = original


# ── Blank secrets in .env ────────────────────────────────────────────────────


def test_blank_internal_key_means_unset() -> None:
    """`.env.example` says to leave INTERNAL_API_KEY empty for local dev.

    An empty value must therefore disable the check. Parsing it as
    `SecretStr('')` would enforce auth against a key no client can send.
    """
    settings = Settings(ai_provider="fake", internal_api_key="", _env_file=None)
    assert settings.internal_api_key is None


def test_blank_api_key_is_rejected_like_a_missing_one() -> None:
    """`AI_API_KEY=` must fail at startup, not at the provider call."""
    with pytest.raises(ValueError, match="AI_API_KEY"):
        Settings(ai_provider="openai-compatible", ai_api_key="   ", _env_file=None)


def test_whitespace_only_internal_key_means_unset() -> None:
    settings = Settings(ai_provider="fake", internal_api_key="   ", _env_file=None)
    assert settings.internal_api_key is None
