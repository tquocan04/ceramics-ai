"""Shared fixtures.

Every test here runs offline. The real provider is never constructed: the app
resolves `get_provider` through a dependency override pointing at
`FakeProvider`, so there is no API key to configure and no network to reach.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.dependencies import get_provider
from app.features.order_extraction.schemas import LLMOrderExtraction
from app.features.order_extraction.service import OrderExtractionService
from app.llm.client import FailureMode, FakeProvider

FIXTURES = Path(__file__).parent / "fixtures"

#: The canonical example from the plan's acceptance criteria (§47 Scenario A).
SAMPLE_DESCRIPTION = (
    "Gấp: 350 đĩa gốm men nâu họa tiết chim hạc cao 4cm, "
    "nung 1300°C, cần xong trong 7 ngày."
)


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cut every `Settings()` in the suite off from the developer's `.env`.

    Without this, tests silently inherit whatever is on the machine. A local
    `AI_TIMEOUT_SECONDS=90` made twenty-eight tests fail with a config error
    that had nothing to do with the code under test -- and, worse, a `.env`
    that happened to match the defaults would let a real misconfiguration pass
    unnoticed. Tests assert on values they state.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith(("AI_", "INTERNAL_API_KEY", "LOG_", "CORS_")):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings() -> Settings:
    """Settings that need no `.env` and no API key."""
    return Settings(ai_provider="fake", ai_model="fake-model", ai_api_key=None)


@pytest.fixture
def sample_extraction() -> LLMOrderExtraction:
    return LLMOrderExtraction(
        product_name="Đĩa gốm",
        quantity=350,
        height_cm=4,
        decoration_pattern="Chim hạc",
        glaze_type="Men nâu",
        firing_temperature_c=1300,
        deadline_days=7,
        evidence={
            "quantity": "350",
            "product_name": "đĩa gốm",
            "glaze_type": "men nâu",
            "decoration_pattern": "họa tiết chim hạc",
            "height_cm": "cao 4cm",
            "firing_temperature_c": "nung 1300°C",
            "deadline_days": "trong 7 ngày",
        },
    )


@pytest.fixture
def make_service(settings: Settings):
    """Build a service around a scripted provider."""

    def _make(
        extraction: LLMOrderExtraction | None = None,
        *,
        failure_mode: FailureMode = FailureMode.NONE,
    ) -> tuple[OrderExtractionService, FakeProvider]:
        provider = FakeProvider(
            responder=(lambda _: extraction) if extraction else None,
            failure_mode=failure_mode,
        )
        return OrderExtractionService(provider, settings), provider

    return _make


@pytest.fixture
def client(sample_extraction: LLMOrderExtraction) -> Iterator[TestClient]:
    """App wired to a fake provider via dependency override."""
    import os

    os.environ.setdefault("AI_PROVIDER", "fake")
    from app.config import get_settings
    from app.main import create_app

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_provider] = lambda: FakeProvider(
        responder=lambda _: sample_extraction
    )
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def load_fixture(name: str) -> Any:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)
