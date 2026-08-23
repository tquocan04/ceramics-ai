"""Guards on the LLM-facing schema and prompt.

These are cheap, pure tests protecting two things that fail *silently*:
evidence disappearing under strict decoding, and the prompt quietly losing an
anti-hallucination rule during an edit.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai.profiles.openai import OpenAIJsonSchemaTransformer

from app.features.order_extraction.prompt import ORDER_EXTRACTION_V2
from app.features.order_extraction.schemas import (
    EXTRACTED_FIELDS,
    Evidence,
    LLMOrderExtraction,
)


def _strict_schema() -> tuple[dict[str, Any], bool]:
    transformer = OpenAIJsonSchemaTransformer(
        LLMOrderExtraction.model_json_schema(), strict=True
    )
    return transformer.walk(), transformer.is_strict_compatible


def test_schema_survives_strict_transformation() -> None:
    _, compatible = _strict_schema()
    assert compatible


def test_evidence_keeps_every_field_under_strict_decoding() -> None:
    """The guard against a future "simplification" to `dict[str, str]`.

    An open dict is rewritten by the transformer to
    `{"properties": {}, "required": [], "additionalProperties": false}` -- an
    object that can carry no keys. Constrained decoding would then make
    evidence impossible to emit, `provenance` would be empty on every request,
    and the review UI's highlights would vanish with no error anywhere.
    """
    schema, _ = _strict_schema()
    definitions = schema.get("$defs", {})
    evidence = definitions.get("Evidence")
    assert evidence is not None, "Evidence should be a named definition"

    properties = set(evidence.get("properties", {}))
    assert properties == set(EXTRACTED_FIELDS), (
        "every extracted field needs an evidence slot the model can actually fill"
    )
    assert properties, "an evidence object with no properties cannot be populated"


def test_schema_contains_no_open_objects() -> None:
    """Generalises the above: any open object collapses under strict mode."""
    schema, _ = _strict_schema()
    offenders: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if isinstance(node.get("additionalProperties"), dict):
                offenders.append(path)
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, f"{path}[{index}]")

    walk(schema, "$")
    assert not offenders, f"open objects lose their contents under strict: {offenders}"


def test_evidence_accepts_the_legacy_list_form() -> None:
    """Old recordings must keep replaying across the schema change."""
    parsed = LLMOrderExtraction.model_validate(
        {
            "quantity": 350,
            "evidence": [
                {"field": "quantity", "text": "350"},
                {"field": "not_a_field", "text": "ignored"},
            ],
        }
    )
    assert parsed.evidence.quantity == "350"
    assert parsed.evidence.height_cm == ""


def test_llm_schema_has_no_dead_fields() -> None:
    """`notes` was generated on every call and read by nothing."""
    assert set(LLMOrderExtraction.model_fields) == set(EXTRACTED_FIELDS) | {"evidence"}


def test_evidence_has_one_slot_per_extracted_field() -> None:
    assert set(Evidence.model_fields) == set(EXTRACTED_FIELDS)


def test_schema_stays_within_its_token_budget() -> None:
    """Stops the schema silently regrowing.

    Note this budget is *larger* than v1's 2052 chars, deliberately. Naming
    all eight evidence slots costs more schema than a free-form
    `list[FieldEvidence]` (390 chars), but it buys strict-decoding safety and
    makes a mis-typed field name unrepresentable -- and it is cheaper where it
    counts: measured on a seven-field order, output drops from 316 to 211
    chars. Schema is prefilled in parallel; output is decoded serially, so
    output is the term that shows up as latency.
    """
    schema, _ = _strict_schema()
    size = len(json.dumps(schema, separators=(",", ":")))
    assert size < 3200, f"schema grew to {size} chars"


def test_prompt_stays_within_its_token_budget() -> None:
    size = len(ORDER_EXTRACTION_V2.instructions)
    assert size < 1700, f"prompt grew to {size} chars"


def test_total_fixed_overhead_fell_against_v1() -> None:
    """Schema plus prompt, the cost paid on every single request.

    v1 measured 2052 + 2866 = 4918 chars. The prompt cut has to more than pay
    for the larger evidence schema, or the change was not worth making.
    """
    schema, _ = _strict_schema()
    total = len(json.dumps(schema, separators=(",", ":"))) + len(
        ORDER_EXTRACTION_V2.instructions
    )
    assert total < 4918, f"fixed overhead {total} chars is no better than v1's 4918"


def test_prompt_keeps_its_load_bearing_rules() -> None:
    """A prompt edit must not quietly drop an anti-hallucination rule.

    The regression suite asserts null on 29 separate fields; those assertions
    only hold because these instructions are present.
    """
    text = ORDER_EXTRACTION_V2.instructions
    for fragment in (
        "Never invent",
        "Never estimate",
        "A null is correct",
        "EXACT substring",
        "Quote the source, not the",
        "đường kính",
    ):
        assert fragment in text, f"prompt lost a load-bearing rule: {fragment!r}"


def test_prompt_version_is_recorded() -> None:
    assert ORDER_EXTRACTION_V2.name == "order-extraction-v2"


def test_evidence_accepts_a_json_encoded_string() -> None:
    """Models routinely serialise a nested object one level too deep.

    Observed in production: the extraction was entirely correct but arrived as
    `"evidence": "{\\"quantity\\": \\"350\\"}"`, and the model repeated it
    byte-for-byte when shown the validation error. Rejecting a correct
    extraction over a quoting habit would be perverse.
    """
    parsed = LLMOrderExtraction.model_validate(
        {"quantity": 350, "evidence": '{"quantity": "350", "height_cm": "cao 4cm"}'}
    )
    assert parsed.evidence.quantity == "350"
    assert parsed.evidence.height_cm == "cao 4cm"


def test_evidence_tolerates_an_empty_string() -> None:
    assert LLMOrderExtraction.model_validate({"evidence": ""}).evidence.quantity == ""


def test_unparseable_evidence_still_fails_validation() -> None:
    """Absorbing known variants must not turn into accepting anything."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        LLMOrderExtraction.model_validate({"evidence": "not json at all"})
