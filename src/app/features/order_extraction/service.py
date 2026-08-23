"""Order extraction pipeline (plan §41, §55).

    description
        -> LLM (typed fields + quoted evidence)
        -> normalise      units, spelled-out numerals
        -> resolve spans  quotes become character offsets
        -> validate       impossible values dropped, odd ones flagged
        -> estimate       deterministic formulas
        -> prioritise     deterministic rule; the model's view kept alongside
    OrderAnalysisResponse

The single LLM step is bounded by an `asyncio.timeout` covering the whole
request; every step after it is pure and offline, which is what lets the
regression suite replay recorded model output through the real pipeline.
"""

from __future__ import annotations

import asyncio
import time

from app.common.enums import ErrorCode, WarningCode
from app.common.responses import AnalysisWarning, RequestMetadata
from app.config import Settings
from app.exceptions import AIServiceError, ProviderTimeout
from app.features.order_extraction.estimator import estimate
from app.features.order_extraction.normalizer import normalize_extraction
from app.features.order_extraction.priority import derive_priority
from app.features.order_extraction.schemas import (
    EXTRACTED_FIELDS,
    ExtractedOrder,
    LLMOrderExtraction,
    OrderAnalysisResponse,
)
from app.features.order_extraction.spans import find_span
from app.features.order_extraction.validators import validate_extraction
from app.llm.provider import LLMProvider
from app.logging import get_logger, truncate
from app.prompts.registry import ORDER_EXTRACTION_V1

log = get_logger(__name__)


class OrderExtractionService:
    def __init__(self, provider: LLMProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings
        self._prompt = ORDER_EXTRACTION_V1

    async def extract(self, description: str, *, language: str = "vi") -> OrderAnalysisResponse:
        text = description.strip()
        if not text:
            raise AIServiceError(ErrorCode.EMPTY_DESCRIPTION)
        if len(text) > self._settings.max_description_chars:
            raise AIServiceError(
                ErrorCode.DESCRIPTION_TOO_LONG,
                f"Mô tả vượt quá {self._settings.max_description_chars} ký tự.",
                details={"length": len(text)},
            )

        started = time.perf_counter()
        budget = self._settings.ai_request_budget_seconds

        log.info(
            "extract.start",
            prompt_version=self._prompt.name,
            language=language,
            description=truncate(text),
        )

        try:
            async with asyncio.timeout(budget):
                result = await self._provider.structured_output(
                    instructions=self._prompt.instructions,
                    user_input=text,
                    output_type=LLMOrderExtraction,
                    deadline_s=budget,
                )
        except TimeoutError as exc:
            # The outer budget is authoritative; a provider mid-flight is cut off.
            raise ProviderTimeout(
                f"Vượt quá ngân sách {budget}s cho một yêu cầu phân tích."
            ) from exc

        response = self.assemble(
            result.value,
            description=text,
            provider=result.provider,
            model=result.model,
        )
        response.metadata = RequestMetadata(
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=result.attempts,
            usage=result.usage,
        )

        log.info(
            "extract.done",
            prompt_version=self._prompt.name,
            latency_ms=response.metadata.latency_ms,
            attempts=response.metadata.attempts,
            warnings=[w.code.value for w in response.warnings],
            missing_fields=response.missing_fields,
        )
        return response

    def assemble(
        self,
        raw: LLMOrderExtraction,
        *,
        description: str,
        provider: str,
        model: str,
    ) -> OrderAnalysisResponse:
        """The pure half of the pipeline: model output in, response out.

        Separated from `extract` so the regression suite can drive recorded
        model output through exactly this code with no network involved.
        """
        warnings: list[AnalysisWarning] = []

        evidence = self._collect_evidence(raw)
        values = {field: getattr(raw, field) for field in EXTRACTED_FIELDS}

        values, normalise_warnings = normalize_extraction(
            values, description=description, evidence=evidence
        )
        warnings.extend(normalise_warnings)

        values, validation_warnings = validate_extraction(
            values, settings=self._settings
        )
        warnings.extend(validation_warnings)

        extracted = ExtractedOrder.model_validate(values)
        provenance, span_warnings = self._resolve_spans(description, evidence, values)
        warnings.extend(span_warnings)

        estimated, estimate_warnings = estimate(
            quantity=extracted.quantity,
            height_cm=extracted.height_cm,
            firing_temperature_c=extracted.firing_temperature_c,
            settings=self._settings,
        )
        warnings.extend(estimate_warnings)

        priority, reason, priority_warnings = derive_priority(
            quantity=extracted.quantity,
            deadline_days=extracted.deadline_days,
            ai_priority=raw.ai_priority,
        )
        warnings.extend(priority_warnings)

        return OrderAnalysisResponse(
            prompt_version=self._prompt.name,
            provider=provider,
            model=model,
            extracted=extracted,
            estimated=estimated,
            priority=priority,
            priority_reason=reason,
            provenance=provenance,
            evidence=evidence,
            ai_priority=raw.ai_priority,
            ai_priority_reason=raw.ai_priority_reason,
            missing_fields=[
                field for field in EXTRACTED_FIELDS if getattr(extracted, field) is None
            ],
            warnings=warnings,
        )

    @staticmethod
    def _collect_evidence(raw: LLMOrderExtraction) -> dict[str, str]:
        """Keep only evidence naming a field we actually publish."""
        return {
            item.field: item.text
            for item in raw.evidence
            if item.field in EXTRACTED_FIELDS and item.text.strip()
        }

    @staticmethod
    def _resolve_spans(
        description: str, evidence: dict[str, str], values: dict[str, object]
    ) -> tuple[dict[str, tuple[int, int]], list[AnalysisWarning]]:
        """Turn quoted evidence into offsets, skipping anything unlocatable."""
        provenance: dict[str, tuple[int, int]] = {}
        warnings: list[AnalysisWarning] = []

        for field, quote in evidence.items():
            if values.get(field) is None:
                # The value was dropped by validation; its highlight would
                # point at a field the UI no longer shows.
                continue
            span = find_span(description, quote)
            if span is None:
                warnings.append(
                    AnalysisWarning(
                        code=WarningCode.EVIDENCE_NOT_FOUND,
                        field=field,
                        message=(
                            f"Không tìm thấy trích dẫn '{truncate(quote, 60)}' "
                            "trong mô tả gốc."
                        ),
                    )
                )
                continue
            provenance[field] = span

        return provenance, warnings
