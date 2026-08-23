"""Order extraction contract.

`ExtractedOrder` and `EstimatedOrderData` are field-for-field identical to the
frontend's `AIExtractedData` / `AIEstimatedData` (frontend/lib/domain/types.ts),
and `OrderAnalysisResponse` is a superset of `AIAnalysisResult`. The backend can
therefore pick five keys off the response and hand them to the review UI with
no mapping layer.

This deviates from the markdown plan §10, which nests `dimensions` and names
the field `pattern`. The markdown was written without the frontend in view; the
UI's shape wins because it is already load-bearing.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.common.enums import Priority
from app.common.responses import SCHEMA_VERSION, AnalysisWarning, RequestMetadata

# ── What the model is asked to produce ───────────────────────────────────────


class Evidence(BaseModel):
    """Verbatim source snippet per extracted field (§11).

    One fixed key per field. Deliberately NOT `list[FieldEvidence]`, and
    emphatically not `dict[str, str]`:

    * A free-form `field: str` lets the model write "height" for `height_cm`.
      `_collect_evidence` then drops it and the review screen loses a
      highlight, with no error raised anywhere.
    * `dict[str, str]` is unusable under strict structured output. Verified
      against the installed transformer: `OpenAIJsonSchemaTransformer(...,
      strict=True)` rewrites an open object to `{"properties": {},
      "required": [], "additionalProperties": false}` -- an object that can
      carry no keys at all. Constrained decoding would then make evidence
      physically impossible to emit, and `provenance` would come back empty on
      every request with nothing to explain why.

    The model quotes text; it is never asked for character offsets. Counting
    characters is exactly what language models are bad at, so offsets are
    resolved deterministically in `spans.py` from these quotes.
    """

    model_config = ConfigDict(extra="ignore")

    # Plain `str` with an empty default, not `str | None`. Strict mode marks
    # every property required regardless, so nullability buys nothing at the
    # wire and costs an `anyOf[string, null]` per field. Measured on the eight
    # fields: 665 chars of schema versus 889, for identical output. An empty
    # string means "no evidence" and is filtered by `_collect_evidence`.
    product_name: str = ""
    quantity: str = ""
    height_cm: str = ""
    width_cm: str = ""
    decoration_pattern: str = ""
    glaze_type: str = ""
    firing_temperature_c: str = ""
    deadline_days: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_model_variants(cls, value: Any) -> Any:
        """Normalise the shapes models actually emit for a nested object.

        Two are absorbed here rather than failed:

        * **A JSON-encoded string.** Observed in production: the model returns
          `"evidence": "{\\"quantity\\": \\"350\\", ...}"` -- the content
          entirely correct, merely serialised one level too deep -- and then
          repeats it byte-for-byte when shown the validation error. Rejecting
          a correct extraction over a quoting habit would be perverse.
        * **The v1 `[{"field": ..., "text": ...}]` list.** Keeps recorded
          replay fixtures valid across the schema change.

        Anything still unparseable falls through to normal validation, so a
        genuinely malformed payload is still reported.
        """
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return {}
            try:
                value = json.loads(text)
            except json.JSONDecodeError:
                return value

        if isinstance(value, list):
            return {
                item["field"]: item["text"]
                for item in value
                if isinstance(item, dict) and "field" in item and "text" in item
            }
        return value


class LLMOrderExtraction(BaseModel):
    """The only object the LLM produces.

    Note what is absent: no estimates, no character offsets, no priority, no
    free-text notes. Estimates and priority are computed deterministically
    downstream (§4, §13, §14); `notes` was generated on every call and read by
    nothing.

    Field descriptions are omitted except where the name genuinely
    under-specifies the field. `quantity: "Number of units ordered."` restates
    its own name at ~8 tokens, on every request, forever. Semantics belong in
    the prompt; the schema carries shape.
    """

    model_config = ConfigDict(extra="ignore")

    product_name: str | None = None
    quantity: int | None = None
    height_cm: float | None = None
    width_cm: float | None = Field(
        default=None, description="Width or diameter (đường kính), in cm."
    )
    decoration_pattern: str | None = None
    glaze_type: str | None = None
    firing_temperature_c: int | None = None
    deadline_days: int | None = None

    evidence: Evidence = Field(
        default_factory=Evidence,
        description="Exact source substring for each field you filled.",
    )


# ── What the API returns ─────────────────────────────────────────────────────


class ExtractedOrder(BaseModel):
    """Mirrors frontend `AIExtractedData` exactly. Do not reorder or rename."""

    product_name: str | None = None
    quantity: int | None = None
    height_cm: float | None = None
    width_cm: float | None = None
    decoration_pattern: str | None = None
    glaze_type: str | None = None
    firing_temperature_c: int | None = None
    deadline_days: int | None = None


class EstimatedOrderData(BaseModel):
    """Mirrors frontend `AIEstimatedData` exactly."""

    clay_kg: float | None = None
    glaze_kg: float | None = None
    firing_duration_hours: float | None = None


class OrderExtractionRequest(BaseModel):
    description: str = Field(min_length=1, description="Raw customer order text.")
    language: str = Field(default="vi", description="BCP-47-ish hint for the prompt.")


class OrderAnalysisResponse(BaseModel):
    """Superset of the frontend's `AIAnalysisResult`.

    `extracted`, `estimated`, `priority`, `priority_reason` and `provenance`
    together *are* an `AIAnalysisResult`.
    """

    schema_version: str = SCHEMA_VERSION
    prompt_version: str
    provider: str
    model: str

    extracted: ExtractedOrder
    estimated: EstimatedOrderData
    priority: Priority | None = None
    priority_reason: str | None = None
    #: field name -> [start, end) offsets into the original description.
    provenance: dict[str, tuple[int, int]] = Field(default_factory=dict)

    #: Debug aid: the model's quoted snippet per field, pre-resolution.
    evidence: dict[str, str] = Field(default_factory=dict)

    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    metadata: RequestMetadata = Field(default_factory=RequestMetadata)


#: The eight fields the review UI renders, in display order.
EXTRACTED_FIELDS: tuple[str, ...] = tuple(ExtractedOrder.model_fields)
