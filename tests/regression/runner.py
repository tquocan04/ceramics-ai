"""Field-level scoring for the golden dataset (plan §40).

Exact string equality is the wrong bar for free text: a model that answers
"Đĩa" instead of "Đĩa gốm" has understood the order. But it is exactly the
right bar for numbers and for nulls -- a null expectation asserts the model
did NOT invent a value, which is the property most worth protecting.

So comparison is per-field:

    numeric / enum   exact
    null expected    exact, and reported separately as the hallucination rate
    free text        diacritic- and case-insensitive, against an `accept` list
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.features.order_extraction.normalizer import fold
from app.features.order_extraction.schemas import OrderAnalysisResponse

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

NUMERIC_FIELDS = frozenset(
    {"quantity", "height_cm", "width_cm", "firing_temperature_c", "deadline_days"}
)
TEXT_FIELDS = frozenset({"product_name", "decoration_pattern", "glaze_type"})


@dataclass(frozen=True, slots=True)
class Case:
    id: str
    description: str
    expected: dict[str, Any]
    accept: dict[str, list[str]] = field(default_factory=dict)
    expected_priority: str | None = None
    expected_warnings: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FieldOutcome:
    case_id: str
    field: str
    expected: Any
    actual: Any
    passed: bool
    kind: str  # numeric | text | null | priority | warning


def load_cases(name: str = "order_extraction_cases.json") -> list[Case]:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return [
        Case(
            id=raw["id"],
            description=raw["description"],
            expected=raw.get("expected", {}),
            accept=raw.get("accept", {}),
            expected_priority=raw.get("expected_priority"),
            expected_warnings=raw.get("expected_warnings", []),
            tags=raw.get("tags", []),
        )
        for raw in payload["cases"]
    ]


def _text_matches(expected: str, actual: Any, accepted: list[str]) -> bool:
    if not isinstance(actual, str):
        return False
    candidates = {fold(expected)} | {fold(a) for a in accepted}
    folded_actual = fold(actual).strip()
    if folded_actual in candidates:
        return True
    # Tolerate a qualifier the model added or dropped ("Đĩa" vs "Đĩa gốm").
    return any(
        folded_actual in candidate or candidate in folded_actual
        for candidate in candidates
    )


def _numeric_matches(expected: Any, actual: Any) -> bool:
    if actual is None:
        return False
    try:
        return abs(float(expected) - float(actual)) < 1e-6
    except (TypeError, ValueError):
        return False


def score_case(case: Case, response: OrderAnalysisResponse) -> Iterator[FieldOutcome]:
    """Yield one outcome per asserted field."""
    extracted = response.extracted.model_dump()

    for name, expected in case.expected.items():
        actual = extracted.get(name)

        if expected is None:
            # The anti-hallucination assertion: absence must stay absence.
            yield FieldOutcome(case.id, name, None, actual, actual is None, "null")
        elif name in NUMERIC_FIELDS:
            yield FieldOutcome(
                case.id, name, expected, actual, _numeric_matches(expected, actual), "numeric"
            )
        elif name in TEXT_FIELDS:
            passed = _text_matches(expected, actual, case.accept.get(name, []))
            yield FieldOutcome(case.id, name, expected, actual, passed, "text")
        else:
            yield FieldOutcome(
                case.id, name, expected, actual, expected == actual, "text"
            )

    if case.expected_priority is not None:
        actual_priority = response.priority.value if response.priority else None
        yield FieldOutcome(
            case.id,
            "priority",
            case.expected_priority,
            actual_priority,
            actual_priority == case.expected_priority,
            "priority",
        )

    for code in case.expected_warnings:
        present = any(w.code.value == code for w in response.warnings)
        yield FieldOutcome(case.id, f"warning:{code}", code, present, present, "warning")


def summarise(outcomes: list[FieldOutcome]) -> dict[str, Any]:
    """Per-field and per-kind accuracy, plus the list of failures."""
    by_field: dict[str, dict[str, int]] = {}
    by_kind: dict[str, dict[str, int]] = {}

    for outcome in outcomes:
        for bucket, key in ((by_field, outcome.field), (by_kind, outcome.kind)):
            stats = bucket.setdefault(key, {"passed": 0, "total": 0})
            stats["total"] += 1
            stats["passed"] += int(outcome.passed)

    def with_rate(bucket: dict[str, dict[str, int]]) -> dict[str, Any]:
        return {
            key: {**stats, "accuracy": round(stats["passed"] / stats["total"], 4)}
            for key, stats in sorted(bucket.items())
        }

    passed = sum(o.passed for o in outcomes)
    return {
        "total_assertions": len(outcomes),
        "passed": passed,
        "accuracy": round(passed / len(outcomes), 4) if outcomes else 0.0,
        "by_field": with_rate(by_field),
        "by_kind": with_rate(by_kind),
        "failures": [
            {
                "case": o.case_id,
                "field": o.field,
                "expected": o.expected,
                "actual": o.actual,
            }
            for o in outcomes
            if not o.passed
        ],
    }


def format_table(summary: dict[str, Any]) -> str:
    lines = [
        "",
        f"Order extraction regression: {summary['passed']}/{summary['total_assertions']} "
        f"assertions ({summary['accuracy']:.1%})",
        "",
        f"  {'field':<26} {'pass':>6} {'total':>6}  accuracy",
        f"  {'-' * 26} {'-' * 6} {'-' * 6}  --------",
    ]
    for name, stats in summary["by_field"].items():
        lines.append(
            f"  {name:<26} {stats['passed']:>6} {stats['total']:>6}  {stats['accuracy']:>7.1%}"
        )
    lines.append("")
    for kind, stats in summary["by_kind"].items():
        lines.append(f"  [{kind}] {stats['passed']}/{stats['total']} ({stats['accuracy']:.1%})")
    if summary["failures"]:
        lines.extend(["", "  failures:"])
        lines.extend(
            f"    {f['case']}.{f['field']}: expected {f['expected']!r}, got {f['actual']!r}"
            for f in summary["failures"]
        )
    return "\n".join(lines) + "\n"
