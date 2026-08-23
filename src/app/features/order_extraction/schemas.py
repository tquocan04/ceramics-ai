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

from pydantic import BaseModel, ConfigDict, Field

from app.common.enums import Priority
from app.common.responses import SCHEMA_VERSION, AnalysisWarning, RequestMetadata

# ── What the model is asked to produce ───────────────────────────────────────


class FieldEvidence(BaseModel):
    """The verbatim source snippet backing one extracted field (§11).

    The model quotes text; it is never asked for character offsets. Counting
    characters is exactly what language models are bad at, so offsets are
    resolved deterministically in `spans.py` from these quotes.
    """

    model_config = ConfigDict(extra="ignore")

    field: str = Field(description="Name of the extracted field this supports.")
    text: str = Field(description="Exact substring copied from the description.")


class LLMOrderExtraction(BaseModel):
    """The only object the LLM produces.

    Note what is absent: no estimates, no character offsets, and the priority is
    advisory. Those are computed deterministically downstream (§4, §13, §14).
    """

    model_config = ConfigDict(extra="ignore")

    product_name: str | None = Field(
        default=None, description="Product type, e.g. 'Bình gốm', 'Đĩa gốm'."
    )
    quantity: int | None = Field(default=None, description="Number of units ordered.")
    height_cm: float | None = Field(default=None, description="Height in centimetres.")
    width_cm: float | None = Field(
        default=None, description="Width or diameter in centimetres."
    )
    decoration_pattern: str | None = Field(
        default=None, description="Decorative motif, e.g. 'Hoa sen', 'Chim hạc'."
    )
    glaze_type: str | None = Field(
        default=None, description="Glaze, e.g. 'Men lam', 'Men nâu'."
    )
    firing_temperature_c: int | None = Field(
        default=None, description="Peak firing temperature in Celsius."
    )
    deadline_days: int | None = Field(
        default=None, description="Days from now until delivery is required."
    )
    notes: str | None = Field(
        default=None, description="Any remaining requirement not covered above."
    )

    evidence: list[FieldEvidence] = Field(
        default_factory=list,
        description="One entry per non-null field, quoting the source text.",
    )
    ai_priority: Priority | None = Field(
        default=None, description="Suggested priority. Advisory only."
    )
    ai_priority_reason: str | None = Field(
        default=None, description="One short business sentence. No reasoning trace."
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
    #: What the model would have chosen, kept beside the deterministic value.
    ai_priority: Priority | None = None
    ai_priority_reason: str | None = None

    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[AnalysisWarning] = Field(default_factory=list)
    metadata: RequestMetadata = Field(default_factory=RequestMetadata)


#: The eight fields the review UI renders, in display order.
EXTRACTED_FIELDS: tuple[str, ...] = tuple(ExtractedOrder.model_fields)
