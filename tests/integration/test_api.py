"""End-to-end HTTP behaviour, with the provider faked.

These prove the wiring the plan's acceptance criteria depend on: the contract
shape the frontend consumes, and the error envelope for each failure mode.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.common.enums import ErrorCode
from app.dependencies import get_provider
from app.features.order_extraction.schemas import ExtractedOrder, LLMOrderExtraction
from app.llm.client import FailureMode, FakeProvider
from tests.conftest import SAMPLE_DESCRIPTION


def test_health_is_open_and_reports_config(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "ceramics-ai-service"
    assert "model" in body and "provider" in body


def test_extract_returns_the_frontend_contract(client: TestClient) -> None:
    response = client.post(
        "/v1/orders/extract",
        json={"description": SAMPLE_DESCRIPTION, "language": "vi"},
    )
    assert response.status_code == 200
    body = response.json()

    # Plan §47 Scenario A.
    assert body["extracted"] == {
        "product_name": "Đĩa gốm",
        "quantity": 350,
        "height_cm": 4.0,
        "width_cm": None,
        "decoration_pattern": "Chim hạc",
        "glaze_type": "Men nâu",
        "firing_temperature_c": 1300,
        "deadline_days": 7,
    }
    assert body["estimated"]["clay_kg"] == 36.0
    assert body["estimated"]["glaze_kg"] == 2.4
    assert body["estimated"]["firing_duration_hours"] == 10.5
    assert body["priority"] == "URGENT"
    assert body["prompt_version"] == "order-extraction-v1"
    assert body["schema_version"] == "1.0"


def test_extracted_keys_match_the_frontend_type_exactly(client: TestClient) -> None:
    """AIExtractedData drift would silently break the review screen."""
    response = client.post("/v1/orders/extract", json={"description": SAMPLE_DESCRIPTION})
    assert set(response.json()["extracted"]) == set(ExtractedOrder.model_fields)


def test_provenance_spans_slice_back_to_the_quoted_text(client: TestClient) -> None:
    """Every highlight the UI draws must land on the right characters."""
    response = client.post("/v1/orders/extract", json={"description": SAMPLE_DESCRIPTION})
    body = response.json()
    assert body["provenance"], "expected at least one resolved span"

    for field, (start, end) in body["provenance"].items():
        sliced = SAMPLE_DESCRIPTION[start:end]
        quoted = body["evidence"][field]
        assert sliced.casefold() == quoted.casefold(), f"{field}: {sliced!r} != {quoted!r}"


def test_empty_description_is_rejected(client: TestClient) -> None:
    response = client.post("/v1/orders/extract", json={"description": "   "})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.EMPTY_DESCRIPTION


def test_missing_description_uses_the_shared_error_envelope(client: TestClient) -> None:
    response = client.post("/v1/orders/extract", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize(
    ("mode", "status", "code"),
    [
        (FailureMode.TIMEOUT, 504, ErrorCode.AI_TIMEOUT),
        (FailureMode.PROVIDER_ERROR, 502, ErrorCode.AI_PROVIDER_ERROR),
        (FailureMode.INVALID_JSON, 502, ErrorCode.AI_INVALID_JSON),
        (FailureMode.SCHEMA_INVALID, 422, ErrorCode.AI_SCHEMA_VALIDATION_FAILED),
    ],
)
def test_provider_failures_map_to_stable_codes(
    client: TestClient, mode: FailureMode, status: int, code: ErrorCode
) -> None:
    """Plan §6.5 / Scenario H: fail cleanly, never with a stack trace."""
    client.app.dependency_overrides[get_provider] = lambda: FakeProvider(
        failure_mode=mode
    )
    response = client.post("/v1/orders/extract", json={"description": SAMPLE_DESCRIPTION})
    assert response.status_code == status
    body = response.json()
    assert body["error"]["code"] == code
    assert body["error"]["message"]
    assert "Traceback" not in response.text


def test_missing_values_stay_null(client: TestClient) -> None:
    """Plan §47 Scenario B: the model must not fill in what was never said."""
    description = "Tạo 200 bình gốm men lam họa tiết sen."
    client.app.dependency_overrides[get_provider] = lambda: FakeProvider(
        responder=lambda _: LLMOrderExtraction(
            product_name="Bình gốm",
            quantity=200,
            glaze_type="Men lam",
            decoration_pattern="Hoa sen",
            evidence=[
                {"field": "quantity", "text": "200"},
                {"field": "glaze_type", "text": "men lam"},
            ],
        )
    )
    response = client.post("/v1/orders/extract", json={"description": description})
    body = response.json()

    assert body["extracted"]["quantity"] == 200
    assert body["extracted"]["firing_temperature_c"] is None
    assert body["extracted"]["deadline_days"] is None
    assert set(body["missing_fields"]) >= {
        "firing_temperature_c",
        "deadline_days",
        "height_cm",
        "width_cm",
    }
    # No temperature means no firing estimate, and we say so rather than guess.
    assert body["estimated"]["firing_duration_hours"] is None


def test_openapi_documents_the_contract(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/v1/orders/extract" in schema["paths"]
    assert "/health" in schema["paths"]


# ── Real dependency wiring ───────────────────────────────────────────────────


def test_real_provider_wiring_resolves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise `get_provider` for real, with no dependency override.

    Every other test overrides the provider, which skips `_build_provider`
    entirely -- and that is exactly where an unhashable-Settings cache bug hid.
    A fake provider with no scripted response must fail as a clean 502, proving
    the request reached the provider rather than dying in the wiring.
    """
    from app.config import get_settings
    from app.dependencies import _build_provider
    from app.main import create_app

    monkeypatch.setenv("AI_PROVIDER", "fake")
    get_settings.cache_clear()
    _build_provider.cache_clear()

    app = create_app()
    with TestClient(app) as unoverridden:
        response = unoverridden.post(
            "/v1/orders/extract", json={"description": SAMPLE_DESCRIPTION}
        )

    assert response.status_code == 502, response.text
    assert response.json()["error"]["code"] == ErrorCode.AI_PROVIDER_ERROR

    get_settings.cache_clear()
    _build_provider.cache_clear()


def test_provider_is_built_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh HTTP client per request would leak connections."""
    from app.config import get_settings
    from app.dependencies import _build_provider

    monkeypatch.setenv("AI_PROVIDER", "fake")
    get_settings.cache_clear()
    _build_provider.cache_clear()

    assert _build_provider() is _build_provider()

    get_settings.cache_clear()
    _build_provider.cache_clear()
