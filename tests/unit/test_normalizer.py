"""Normalisation corrects units and flags vagueness -- it never invents data."""

from __future__ import annotations

import pytest

from app.common.enums import WarningCode
from app.features.order_extraction.normalizer import (
    normalize_extraction,
    parse_vietnamese_number,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ba trăm năm mươi", 350),
        ("hai trăm", 200),
        ("một trăm hai mươi lăm", 125),
        ("mười lăm", 15),
        ("mười", 10),
        ("hai mươi", 20),
        ("ba mươi tư", 34),
        ("một trăm linh năm", 105),
        ("hai nghìn", 2000),
        ("một nghìn năm trăm", 1500),
        ("sáu mươi", 60),
        ("chín", 9),
    ],
)
def test_spelled_out_numerals(text: str, expected: int) -> None:
    assert parse_vietnamese_number(text) == expected


def test_no_numeral_returns_none() -> None:
    assert parse_vietnamese_number("bình gốm men lam") is None
    assert parse_vietnamese_number("") is None


def _run(values: dict[str, object], description: str, evidence: dict[str, str]):
    return normalize_extraction(values, description=description, evidence=evidence)


def test_millimetres_are_converted_to_centimetres() -> None:
    out, warnings = _run(
        {"height_cm": 40.0}, "Đĩa cao 40mm.", {"height_cm": "cao 40mm"}
    )
    assert out["height_cm"] == 4.0
    assert [w.code for w in warnings] == [WarningCode.UNIT_CORRECTED]


def test_already_converted_height_is_left_alone() -> None:
    """The model usually converts correctly; we must not double-convert."""
    out, warnings = _run(
        {"height_cm": 4.0}, "Đĩa cao 40mm.", {"height_cm": "cao 40mm"}
    )
    assert out["height_cm"] == 4.0
    assert warnings == []


def test_metres_are_converted() -> None:
    out, _ = _run({"height_cm": 1.2}, "Bình cao 1.2m.", {"height_cm": "cao 1.2m"})
    assert out["height_cm"] == 120.0


def test_thousands_separator_in_temperature() -> None:
    out, warnings = _run(
        {"firing_temperature_c": 1},
        "Nung khoảng 1.280°C.",
        {"firing_temperature_c": "nung khoảng 1.280°C"},
    )
    assert out["firing_temperature_c"] == 1280
    assert warnings[0].code is WarningCode.UNIT_CORRECTED


def test_plain_temperature_untouched() -> None:
    out, warnings = _run(
        {"firing_temperature_c": 1300},
        "Nung 1300°C.",
        {"firing_temperature_c": "nung 1300°C"},
    )
    assert out["firing_temperature_c"] == 1300
    assert warnings == []


def test_spelled_week_becomes_days() -> None:
    out, _ = _run(
        {"deadline_days": 1},
        "Cần trong một tuần.",
        {"deadline_days": "trong một tuần"},
    )
    assert out["deadline_days"] == 7


def test_numeric_weeks_become_days() -> None:
    out, _ = _run(
        {"deadline_days": 2}, "Giao trong 2 tuần.", {"deadline_days": "trong 2 tuần"}
    )
    assert out["deadline_days"] == 14


def test_half_month_becomes_fifteen_days() -> None:
    out, _ = _run(
        {"deadline_days": 1}, "Xong trong nửa tháng.", {"deadline_days": "nửa tháng"}
    )
    assert out["deadline_days"] == 15


def test_days_already_correct_are_untouched() -> None:
    out, warnings = _run(
        {"deadline_days": 7}, "Xong trong 7 ngày.", {"deadline_days": "trong 7 ngày"}
    )
    assert out["deadline_days"] == 7
    assert warnings == []


def test_spelled_quantity_is_recovered_when_model_returns_null() -> None:
    out, warnings = _run(
        {"quantity": None},
        "Đặt ba trăm năm mươi đĩa gốm.",
        {"quantity": "ba trăm năm mươi"},
    )
    assert out["quantity"] == 350
    assert warnings[0].code is WarningCode.UNIT_CORRECTED


def test_vague_quantity_is_flagged_and_stays_null() -> None:
    """Plan Scenario D: never invent a number for 'khoảng vài trăm'."""
    out, warnings = _run(
        {"quantity": None, "deadline_days": None},
        "Làm khoảng vài trăm cái, càng sớm càng tốt.",
        {},
    )
    assert out["quantity"] is None
    assert out["deadline_days"] is None
    codes = {w.code for w in warnings}
    assert WarningCode.AMBIGUOUS_QUANTITY in codes
    assert WarningCode.AMBIGUOUS_DEADLINE in codes


def test_vague_phrase_with_a_value_still_warns() -> None:
    """A concrete number under vague wording is a hallucination candidate."""
    _, warnings = _run(
        {"quantity": 300}, "Làm khoảng vài trăm cái.", {"quantity": "vài trăm"}
    )
    assert any(w.code is WarningCode.AMBIGUOUS_QUANTITY for w in warnings)


def test_clean_order_produces_no_warnings() -> None:
    description = (
        "Gấp: 350 đĩa gốm men nâu họa tiết chim hạc cao 4cm, "
        "nung 1300°C, cần xong trong 7 ngày."
    )
    _, warnings = _run(
        {
            "quantity": 350,
            "height_cm": 4.0,
            "width_cm": None,
            "firing_temperature_c": 1300,
            "deadline_days": 7,
        },
        description,
        {
            "quantity": "350",
            "height_cm": "cao 4cm",
            "firing_temperature_c": "nung 1300°C",
            "deadline_days": "trong 7 ngày",
        },
    )
    assert warnings == []
