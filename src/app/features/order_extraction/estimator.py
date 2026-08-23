"""Deterministic material estimates (plan §13).

Plan §13 ranks estimation strategies: a formula beats a lookup table, which
beats asking the model. Clay and glaze mass are simple functions of quantity
and size, so the LLM is never consulted -- it would give a different answer
every call for arithmetic we can do exactly.

The constants come from `frontend/lib/mock/ai.ts` and live in `Settings`, so
the workshop can recalibrate them from `.env` without a code change.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.common.enums import WarningCode
from app.common.responses import AnalysisWarning
from app.config import Settings
from app.features.order_extraction.schemas import EstimatedOrderData

__all__ = ["estimate"]


def _round1(value: float) -> float:
    """Round to 1dp, half away from zero.

    Not `round()`: Python rounds half to even, so 9.25 would become 9.2 while
    the frontend's `Math.round` gives 9.3. A tenth of an hour is harmless on
    its own, but a figure that differs between the two implementations of the
    same formula is a bug report waiting to happen.
    """
    return float(Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def estimate(
    *,
    quantity: int | None,
    height_cm: float | None,
    firing_temperature_c: int | None,
    settings: Settings,
) -> tuple[EstimatedOrderData, list[AnalysisWarning]]:
    """Compute material and time estimates from validated inputs.

    A null input yields a null estimate plus a warning -- guessing here would
    put a fabricated number in front of a manager as if it were derived.
    """
    warnings: list[AnalysisWarning] = []

    clay_kg: float | None = None
    glaze_kg: float | None = None
    firing_hours: float | None = None

    if quantity is None:
        warnings.append(
            AnalysisWarning(
                code=WarningCode.ESTIMATE_UNAVAILABLE,
                field="clay_kg",
                message="Chưa có số lượng nên không ước lượng được nguyên liệu.",
            )
        )
    else:
        # Height is the only optional input with a sensible default: an
        # unstated size is assumed to be a typical mid-size vessel.
        height = height_cm if height_cm is not None else settings.default_height_cm
        clay_kg = _round1(
            quantity
            * settings.clay_kg_per_unit
            * (height / settings.clay_reference_height_cm)
        )
        glaze_kg = _round1(clay_kg / settings.glaze_clay_ratio)

    if firing_temperature_c is None:
        warnings.append(
            AnalysisWarning(
                code=WarningCode.ESTIMATE_UNAVAILABLE,
                field="firing_duration_hours",
                message="Chưa có nhiệt độ nung nên không ước lượng được thời gian nung.",
            )
        )
    else:
        firing_hours = _round1(
            settings.firing_base_hours
            + (firing_temperature_c - settings.firing_temp_baseline_c)
            / settings.firing_degrees_per_hour
        )

    return (
        EstimatedOrderData(
            clay_kg=clay_kg,
            glaze_kg=glaze_kg,
            firing_duration_hours=firing_hours,
        ),
        warnings,
    )
