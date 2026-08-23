"""Build the replay fixture from the golden cases.

Run:  python -m tests.regression.seed_recordings

Replay recordings stand in for the model so `pytest` exercises the whole
post-LLM pipeline offline. For most cases the recorded output equals the
expected result -- there the recording pins span resolution, estimation,
priority and missing-field reporting.

The interesting entries are the `_RAW_OVERRIDES`: cases where a real model
plausibly returns an unconverted value ("cao 40mm" -> height_cm=40). Those
recordings are what prove the normaliser actually corrects the mistake rather
than the prompt merely asking it not to happen.

`record_live.py` overwrites this file with genuine model output.
"""

from __future__ import annotations

import json
from typing import Any

from app.features.order_extraction.spans import find_span
from tests.regression.runner import FIXTURES, load_cases

OUTPUT = FIXTURES / "recorded" / "order_extraction_replay.json"

#: Fields the model reports verbatim from the source, before normalisation.
#: value = (field, raw_value, evidence snippet as it appears in the text)
_RAW_OVERRIDES: dict[str, list[tuple[str, Any, str]]] = {
    "vi-order-005-spelled-quantity": [("quantity", None, "ba trăm năm mươi")],
    "vi-order-008-height-mm": [("height_cm", 40, "cao 40mm")],
    "vi-order-010-height-metres": [("height_cm", 1.2, "cao 1.2m")],
    "vi-order-012-temp-thousands-separator": [
        ("firing_temperature_c", 1, "nung khoảng 1.280°C")
    ],
    "vi-order-014-deadline-one-week": [("deadline_days", 1, "trong một tuần")],
    "vi-order-015-deadline-two-weeks": [("deadline_days", 2, "trong 2 tuần")],
    "vi-order-016-deadline-half-month": [("deadline_days", 1, "nửa tháng")],
    "vi-order-017-deadline-one-month": [("deadline_days", 1, "trong 1 tháng")],
}

#: Evidence snippets that are not simply `str(value)` in the source text.
_EVIDENCE_HINTS: dict[str, dict[str, str]] = {
    "vi-order-001-full": {
        "product_name": "đĩa gốm",
        "height_cm": "cao 4cm",
        "decoration_pattern": "họa tiết chim hạc",
        "glaze_type": "men nâu",
        "firing_temperature_c": "nung 1300°C",
        "deadline_days": "trong 7 ngày",
    },
    "vi-order-002-example-vase": {
        "product_name": "Bình gốm",
        "height_cm": "cao 35cm",
        "decoration_pattern": "họa tiết sen",
        "glaze_type": "men lam",
        "firing_temperature_c": "1280°C",
        "deadline_days": "trong 10 ngày",
    },
    "vi-order-003-example-bowl": {
        "product_name": "chén gốm",
        "height_cm": "cao 8cm",
        "decoration_pattern": "họa tiết tre",
        "glaze_type": "men trắng",
        "firing_temperature_c": "nung 1250 độ C",
        "deadline_days": "trong 21 ngày",
    },
    "vi-order-004-example-jar": {
        "product_name": "lọ gốm",
        "height_cm": "cao 22cm",
        "decoration_pattern": "họa tiết mây",
        "glaze_type": "men rạn",
        "firing_temperature_c": "nung 1220 độ",
        "deadline_days": "18 ngày",
    },
    "vi-order-018-missing-temperature": {
        "product_name": "bình gốm",
        "decoration_pattern": "họa tiết sen",
        "glaze_type": "men lam",
    },
    "vi-order-020-only-quantity-and-product": {"product_name": "lọ gốm"},
    "vi-order-023-diameter": {"width_cm": "đường kính 15cm", "glaze_type": "men trắng"},
    "vi-order-024-height-and-width": {"height_cm": "cao 25cm", "width_cm": "rộng 12cm"},
    "vi-order-026-unrelated-notes": {
        "decoration_pattern": "họa tiết sen",
        "glaze_type": "men lam",
        "height_cm": "cao 28cm",
        "deadline_days": "trong 16 ngày",
    },
    "vi-order-030-single-item": {"height_cm": "cao 40cm"},
}


def _evidence_for(field: str, value: Any, description: str, hint: str | None) -> str | None:
    """Pick a snippet that genuinely occurs in the description."""
    if hint and find_span(description, hint):
        return hint
    if value is None:
        return None
    for candidate in (str(value), str(int(value)) if isinstance(value, float) else None):
        if candidate and find_span(description, candidate):
            return candidate
    return None


def build() -> dict[str, Any]:
    recordings: dict[str, Any] = {}

    for case in load_cases():
        values: dict[str, Any] = {
            name: value for name, value in case.expected.items() if value is not None
        }
        hints = _EVIDENCE_HINTS.get(case.id, {})

        for name, raw_value, snippet in _RAW_OVERRIDES.get(case.id, []):
            values[name] = raw_value
            hints[name] = snippet

        evidence = {}
        for name, value in values.items():
            snippet = _evidence_for(name, value, case.description, hints.get(name))
            if snippet:
                evidence[name] = snippet

        recordings[case.id] = {**values, "evidence": evidence}

    return {
        "source": "seeded",
        "note": (
            "Synthetic model output for offline replay. Regenerate genuine "
            "recordings with `python -m tests.regression.record_live`."
        ),
        "recordings": recordings,
    }


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    payload = build()
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"wrote {len(payload['recordings'])} recordings to {OUTPUT}")


if __name__ == "__main__":
    main()
