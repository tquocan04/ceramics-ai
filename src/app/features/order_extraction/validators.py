"""Semantic validation (plan §15, §16).

Pydantic checks shape; this checks *meaning*. `firing_temperature_c = 3000` is
a perfectly valid integer and a kiln that does not exist.

The severity split matters. A value that is impossible (quantity <= 0) is
dropped to null so no downstream estimate is computed from nonsense. A value
that is merely suspicious (a 3000°C kiln, a two-year deadline) is kept and
flagged, because the manager reviewing the screen knows the workshop better
than this rule does. Only a total absence of usable data raises.
"""

from __future__ import annotations

from typing import Any

from app.common.enums import WarningCode
from app.common.responses import AnalysisWarning
from app.config import Settings

__all__ = ["validate_extraction"]

#: Above this, a quantity is more likely a misparse than a real order.
_MAX_PLAUSIBLE_QUANTITY = 100_000
#: Two years out is almost certainly a unit error.
_MAX_PLAUSIBLE_DEADLINE_DAYS = 730
#: A three-metre studio piece is possible; thirty metres is not.
_MAX_PLAUSIBLE_DIMENSION_CM = 300.0


def validate_extraction(
    values: dict[str, Any], *, settings: Settings
) -> tuple[dict[str, Any], list[AnalysisWarning]]:
    """Return sanitised values plus warnings. Never raises for bad content."""
    out = dict(values)
    warnings: list[AnalysisWarning] = []

    def drop(field: str, code: WarningCode, message: str) -> None:
        """Discard an impossible value so nothing is estimated from it."""
        out[field] = None
        warnings.append(AnalysisWarning(code=code, field=field, message=message))

    def flag(field: str, code: WarningCode, message: str) -> None:
        """Keep a suspicious value, but make the reviewer look at it."""
        warnings.append(AnalysisWarning(code=code, field=field, message=message))

    # ── quantity ─────────────────────────────────────────────────────────
    quantity = out.get("quantity")
    if quantity is not None:
        if quantity <= 0:
            drop(
                "quantity",
                WarningCode.QUANTITY_NOT_POSITIVE,
                f"Số lượng phải lớn hơn 0 (nhận được {quantity}).",
            )
        elif quantity > _MAX_PLAUSIBLE_QUANTITY:
            flag(
                "quantity",
                WarningCode.QUANTITY_IMPLAUSIBLE,
                f"Số lượng {quantity} bất thường — cần kiểm tra lại đơn hàng.",
            )

    # ── firing temperature ───────────────────────────────────────────────
    temperature = out.get("firing_temperature_c")
    if temperature is not None:
        if temperature <= 0:
            drop(
                "firing_temperature_c",
                WarningCode.FIRING_TEMPERATURE_OUT_OF_RANGE,
                f"Nhiệt độ nung phải lớn hơn 0 (nhận được {temperature}).",
            )
        elif not (
            settings.firing_temp_min_c <= temperature <= settings.firing_temp_max_c
        ):
            # Kept, not dropped: a specialist kiln may sit outside our defaults.
            flag(
                "firing_temperature_c",
                WarningCode.FIRING_TEMPERATURE_OUT_OF_RANGE,
                f"Nhiệt độ {temperature} độ C nằm ngoài khoảng thông thường "
                f"{settings.firing_temp_min_c}-{settings.firing_temp_max_c} độ C.",
            )

    # ── deadline ─────────────────────────────────────────────────────────
    deadline = out.get("deadline_days")
    if deadline is not None:
        if deadline <= 0:
            drop(
                "deadline_days",
                WarningCode.DEADLINE_NOT_POSITIVE,
                f"Thời hạn phải lớn hơn 0 ngày (nhận được {deadline}).",
            )
        elif deadline > _MAX_PLAUSIBLE_DEADLINE_DAYS:
            flag(
                "deadline_days",
                WarningCode.DEADLINE_IMPLAUSIBLE,
                f"Thời hạn {deadline} ngày bất thường — có thể sai đơn vị.",
            )

    # ── dimensions ───────────────────────────────────────────────────────
    for field, label in (("height_cm", "Chiều cao"), ("width_cm", "Chiều rộng")):
        value = out.get(field)
        if value is None:
            continue
        if value <= 0:
            drop(
                field,
                WarningCode.DIMENSION_NOT_POSITIVE,
                f"{label} phải lớn hơn 0 cm (nhận được {value}).",
            )
        elif value > _MAX_PLAUSIBLE_DIMENSION_CM:
            flag(
                field,
                WarningCode.DIMENSION_IMPLAUSIBLE,
                f"{label} {value} cm bất thường — có thể sai đơn vị.",
            )

    # ── free text ────────────────────────────────────────────────────────
    for field in ("product_name", "decoration_pattern", "glaze_type"):
        value = out.get(field)
        if isinstance(value, str):
            cleaned = value.strip()
            out[field] = cleaned or None

    return out, warnings
