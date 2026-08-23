"""Deterministic normalisation of the model's output (plan §17).

The prompt asks the model to return canonical units already (cm, °C, days).
This module is the *defensive* second pass: it re-reads each field's quoted
evidence and corrects the value when the quote proves the model skipped a
conversion. That matters because "cao 40mm" silently returning `height_cm=40`
is a ten-fold error the review UI cannot spot.

Nothing here invents data. When the source text is genuinely vague
("khoảng vài trăm cái"), the value stays null and a warning explains why --
plan Scenario D.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from app.common.enums import WarningCode
from app.common.responses import AnalysisWarning

__all__ = ["fold", "normalize_extraction", "parse_vietnamese_number"]

# ── Vietnamese numerals ──────────────────────────────────────────────────────

_UNITS: dict[str, int] = {
    "khong": 0,
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "nam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
}
#: Digit words that change form in the ones slot after a tens word.
_UNITS_AFTER_TENS: dict[str, int] = _UNITS | {"lam": 5, "nham": 5, "mot": 1, "tu": 4}
_TENS_MARKER = "muoi"
_HUNDRED = "tram"
_ZERO_FILLERS = frozenset({"linh", "le"})
_SCALES: tuple[tuple[str, int], ...] = (
    ("trieu", 1_000_000),
    ("nghin", 1000),
    ("ngan", 1000),
)


def fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics, for keyword matching only."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.replace("đ", "d")


def _parse_group(tokens: list[str]) -> int | None:
    """Parse a group below one thousand. Returns None if nothing numeric."""
    total = 0
    matched = False
    idx = 0
    n = len(tokens)

    if n >= 2 and tokens[1] == _HUNDRED and tokens[0] in _UNITS:
        total += _UNITS[tokens[0]] * 100
        matched = True
        idx = 2

    if idx < n and tokens[idx] in _ZERO_FILLERS:
        idx += 1
        if idx < n and tokens[idx] in _UNITS_AFTER_TENS:
            total += _UNITS_AFTER_TENS[tokens[idx]]
            matched = True
        return total if matched else None

    if idx < n:
        token = tokens[idx]
        if token == _TENS_MARKER:
            # "mười", "mười lăm"
            total += 10
            matched = True
            idx += 1
            if idx < n and tokens[idx] in _UNITS_AFTER_TENS:
                total += _UNITS_AFTER_TENS[tokens[idx]]
        elif idx + 1 < n and tokens[idx + 1] == _TENS_MARKER and token in _UNITS:
            # "hai mươi", "ba mươi lăm"
            total += _UNITS[token] * 10
            matched = True
            idx += 2
            if idx < n and tokens[idx] in _UNITS_AFTER_TENS:
                total += _UNITS_AFTER_TENS[tokens[idx]]
        elif token in _UNITS:
            total += _UNITS[token]
            matched = True

    return total if matched else None


def parse_vietnamese_number(text: str) -> int | None:
    """'ba trăm năm mươi' -> 350. Returns None when no numeral is present."""
    tokens = [t for t in re.split(r"[^\w]+", fold(text)) if t]
    if not tokens:
        return None

    total = 0
    matched = False
    for word, multiplier in _SCALES:
        if word in tokens:
            cut = tokens.index(word)
            head = _parse_group(tokens[:cut])
            total += (head if head is not None else 1) * multiplier
            matched = True
            tokens = tokens[cut + 1 :]

    tail = _parse_group(tokens)
    if tail is not None:
        total += tail
        matched = True

    return total if matched else None


# ── Ambiguity detection (plan Scenario D) ────────────────────────────────────

_VAGUE_QUANTITY = (
    "vai tram",
    "vai chuc",
    "vai nghin",
    "vai cai",
    "mot it",
    "mot vai",
    "so luong lon",
    "kha nhieu",
)
_VAGUE_DEADLINE = (
    "cang som cang tot",
    "som nhat co the",
    "trong thoi gian ngan",
    "khi nao xong",
)


def _detect_vague(description: str, phrases: tuple[str, ...]) -> str | None:
    folded = fold(description)
    return next((p for p in phrases if p in folded), None)


# ── Unit correction ──────────────────────────────────────────────────────────

_MM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*mm\b", re.IGNORECASE)
_M_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\b(?!m)", re.IGNORECASE)
_WEEK_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*tuan\b")
_MONTH_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*thang\b")
#: 1.280 / 1,280 -- a thousands separator, not a decimal point.
_THOUSANDS_RE = re.compile(r"\b(\d{1,2})[.,](\d{3})\b")


def _as_float(raw: str) -> float:
    return float(raw.replace(",", "."))


def _correct_length(
    value: float | None, evidence: str | None, field: str
) -> tuple[float | None, AnalysisWarning | None]:
    """Catch a millimetre or metre figure the model failed to convert."""
    if value is None or not evidence:
        return value, None

    mm = _MM_RE.search(evidence)
    if mm and abs(_as_float(mm.group(1)) - value) < 1e-6:
        corrected = round(value / 10, 2)
        return corrected, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field=field,
            message=f"Nguồn ghi {mm.group(0).strip()}; đã đổi {value} thành {corrected} cm.",
        )

    metre = _M_RE.search(evidence)
    if metre and abs(_as_float(metre.group(1)) - value) < 1e-6 and value <= 5:
        corrected = round(value * 100, 2)
        return corrected, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field=field,
            message=f"Nguồn ghi {metre.group(0).strip()}; đã đổi {value} thành {corrected} cm.",
        )

    return value, None


def _correct_temperature(
    value: int | None, evidence: str | None
) -> tuple[int | None, AnalysisWarning | None]:
    """'nung 1.280°C' must not become 1."""
    if value is None or not evidence or value >= 100:
        return value, None

    match = _THOUSANDS_RE.search(evidence)
    if match:
        corrected = int(match.group(1) + match.group(2))
        return corrected, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field="firing_temperature_c",
            message=f"Đọc lại '{match.group(0)}' thành {corrected} độ C.",
        )
    return value, None


def _correct_deadline(
    value: int | None, evidence: str | None
) -> tuple[int | None, AnalysisWarning | None]:
    """Weeks and months expressed as-is become days."""
    if value is None or not evidence:
        return value, None

    folded = fold(evidence)

    week = _WEEK_RE.search(folded)
    if week and abs(_as_float(week.group(1)) - value) < 1e-6:
        corrected = int(value * 7)
        return corrected, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field="deadline_days",
            message=f"Nguồn ghi {value} tuần; đã đổi thành {corrected} ngày.",
        )

    # "một tuần" -- a spelled-out week count the model reported verbatim.
    if "tuan" in folded and value <= 8 and not week:
        spelled = parse_vietnamese_number(folded.split("tuan")[0])
        weeks = spelled if spelled else 1
        if value == weeks:
            corrected = weeks * 7
            return corrected, AnalysisWarning(
                code=WarningCode.UNIT_CORRECTED,
                field="deadline_days",
                message=f"Nguồn ghi {weeks} tuần; đã đổi thành {corrected} ngày.",
            )

    if "nua thang" in folded and value <= 1:
        return 15, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field="deadline_days",
            message="Nguồn ghi 'nửa tháng'; đã đổi thành 15 ngày.",
        )

    month = _MONTH_RE.search(folded)
    if month and abs(_as_float(month.group(1)) - value) < 1e-6:
        corrected = int(value * 30)
        return corrected, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field="deadline_days",
            message=f"Nguồn ghi {value} tháng; đã đổi thành {corrected} ngày.",
        )

    return value, None


def _recover_quantity(
    value: int | None, description: str, evidence: str | None
) -> tuple[int | None, AnalysisWarning | None]:
    """Recover a spelled-out quantity the model left null."""
    if value is not None:
        return value, None
    parsed = parse_vietnamese_number(evidence or description)
    if parsed and parsed > 0:
        return parsed, AnalysisWarning(
            code=WarningCode.UNIT_CORRECTED,
            field="quantity",
            message=f"Đọc số lượng viết bằng chữ thành {parsed}.",
        )
    return None, None


def normalize_extraction(
    values: dict[str, Any],
    *,
    description: str,
    evidence: dict[str, str],
) -> tuple[dict[str, Any], list[AnalysisWarning]]:
    """Return corrected field values plus any warnings raised along the way."""
    out = dict(values)
    warnings: list[AnalysisWarning] = []

    def record(field: str, result: tuple[Any, AnalysisWarning | None]) -> None:
        value, warning = result
        out[field] = value
        if warning is not None:
            warnings.append(warning)

    for field in ("height_cm", "width_cm"):
        record(field, _correct_length(out.get(field), evidence.get(field), field))

    record(
        "firing_temperature_c",
        _correct_temperature(
            out.get("firing_temperature_c"), evidence.get("firing_temperature_c")
        ),
    )
    record(
        "deadline_days",
        _correct_deadline(out.get("deadline_days"), evidence.get("deadline_days")),
    )
    record(
        "quantity",
        _recover_quantity(out.get("quantity"), description, evidence.get("quantity")),
    )

    # Vague phrasing is flagged whether or not a value survived: a value that
    # appears despite vague wording may well have been invented.
    phrase = _detect_vague(description, _VAGUE_QUANTITY)
    if phrase is not None:
        warnings.append(
            AnalysisWarning(
                code=WarningCode.AMBIGUOUS_QUANTITY,
                field="quantity",
                message=(
                    f"Mô tả dùng cách nói ước chừng ('{phrase}'). "
                    "Cần xác nhận số lượng chính xác với khách hàng."
                ),
            )
        )

    phrase = _detect_vague(description, _VAGUE_DEADLINE)
    if phrase is not None:
        warnings.append(
            AnalysisWarning(
                code=WarningCode.AMBIGUOUS_DEADLINE,
                field="deadline_days",
                message=(
                    f"Mô tả không nêu thời hạn cụ thể ('{phrase}'). "
                    "Cần xác nhận deadline với khách hàng."
                ),
            )
        )

    return out, warnings
