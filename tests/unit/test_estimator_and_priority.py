"""Estimates and priority must reproduce the numbers the review UI expects.

The frontend mock (frontend/lib/mock/ai.ts) is the reference implementation:
if these drift, the same order suddenly shows different material figures.
"""

from __future__ import annotations

import pytest

from app.common.enums import Priority, WarningCode
from app.config import Settings
from app.features.order_extraction.estimator import estimate
from app.features.order_extraction.priority import derive_priority
from app.features.order_extraction.validators import validate_extraction


@pytest.fixture
def settings() -> Settings:
    return Settings(ai_provider="fake", ai_api_key=None)


# ── Estimation ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("quantity", "height", "temperature", "clay", "glaze", "hours"),
    [
        # The four EXAMPLE_ORDERS from frontend/lib/mock/ai.ts.
        (200, 35.0, 1280, 180.0, 12.0, 10.0),
        (60, 8.0, 1250, 12.3, 0.8, 9.3),
        (350, 4.0, 1300, 36.0, 2.4, 10.5),
        (30, 22.0, 1220, 17.0, 1.1, 8.5),
    ],
)
def test_matches_the_frontend_mock_formulas(
    settings: Settings,
    quantity: int,
    height: float,
    temperature: int,
    clay: float,
    glaze: float,
    hours: float,
) -> None:
    result, warnings = estimate(
        quantity=quantity,
        height_cm=height,
        firing_temperature_c=temperature,
        settings=settings,
    )
    assert result.clay_kg == clay
    assert result.glaze_kg == glaze
    assert result.firing_duration_hours == hours
    assert warnings == []


def test_absent_height_falls_back_to_the_configured_default(settings: Settings) -> None:
    result, _ = estimate(
        quantity=100, height_cm=None, firing_temperature_c=1200, settings=settings
    )
    # 100 * 0.9 * (30/35)
    assert result.clay_kg == 77.1


def test_missing_inputs_produce_null_estimates_not_guesses(settings: Settings) -> None:
    result, warnings = estimate(
        quantity=None, height_cm=None, firing_temperature_c=None, settings=settings
    )
    assert result.clay_kg is None
    assert result.glaze_kg is None
    assert result.firing_duration_hours is None
    assert {w.code for w in warnings} == {WarningCode.ESTIMATE_UNAVAILABLE}


# ── Priority ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("quantity", "days", "expected"),
    [
        (350, 7, Priority.URGENT),   # qty >= 300
        (100, 3, Priority.URGENT),   # days <= 5
        (200, 10, Priority.HIGH),
        (150, 10, Priority.HIGH),
        (30, 18, Priority.LOW),
        (60, 21, Priority.NORMAL),
        (100, 30, Priority.NORMAL),
    ],
)
def test_thresholds_match_the_mock(quantity: int, days: int, expected: Priority) -> None:
    priority, reason, _ = derive_priority(quantity=quantity, deadline_days=days)
    assert priority is expected
    assert reason


def test_absent_deadline_assumes_a_comfortable_horizon() -> None:
    priority, _, _ = derive_priority(quantity=10, deadline_days=None)
    assert priority is Priority.LOW


def test_disagreement_with_the_model_is_recorded() -> None:
    """The rule wins, but the divergence is visible for later calibration."""
    priority, _, warnings = derive_priority(
        quantity=10, deadline_days=30, ai_priority=Priority.URGENT
    )
    assert priority is Priority.LOW
    assert [w.code for w in warnings] == [WarningCode.AI_PRIORITY_OVERRIDDEN]


def test_agreement_produces_no_warning() -> None:
    _, _, warnings = derive_priority(
        quantity=350, deadline_days=7, ai_priority=Priority.URGENT
    )
    assert warnings == []


# ── Semantic validation ──────────────────────────────────────────────────────


def test_impossible_quantity_is_dropped(settings: Settings) -> None:
    """Plan §15: a negative quantity must not reach an estimate."""
    out, warnings = validate_extraction({"quantity": -5}, settings=settings)
    assert out["quantity"] is None
    assert warnings[0].code is WarningCode.QUANTITY_NOT_POSITIVE


def test_out_of_range_temperature_is_kept_but_flagged(settings: Settings) -> None:
    """A specialist kiln may sit outside our defaults; the manager decides."""
    out, warnings = validate_extraction(
        {"firing_temperature_c": 3000}, settings=settings
    )
    assert out["firing_temperature_c"] == 3000
    assert warnings[0].code is WarningCode.FIRING_TEMPERATURE_OUT_OF_RANGE


def test_zero_temperature_is_dropped(settings: Settings) -> None:
    out, _ = validate_extraction({"firing_temperature_c": 0}, settings=settings)
    assert out["firing_temperature_c"] is None


def test_negative_deadline_is_dropped(settings: Settings) -> None:
    out, warnings = validate_extraction({"deadline_days": -3}, settings=settings)
    assert out["deadline_days"] is None
    assert warnings[0].code is WarningCode.DEADLINE_NOT_POSITIVE


def test_blank_free_text_becomes_null(settings: Settings) -> None:
    out, _ = validate_extraction(
        {"product_name": "   ", "glaze_type": " Men lam "}, settings=settings
    )
    assert out["product_name"] is None
    assert out["glaze_type"] == "Men lam"


def test_valid_input_passes_clean(settings: Settings) -> None:
    values = {
        "quantity": 350,
        "firing_temperature_c": 1300,
        "deadline_days": 7,
        "height_cm": 4.0,
    }
    out, warnings = validate_extraction(values, settings=settings)
    assert out == values
    assert warnings == []
