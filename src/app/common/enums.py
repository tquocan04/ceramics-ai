"""Enums shared across the service.

`Priority` and the AI error codes are transcribed from the frontend so the two
sides cannot drift: see frontend/lib/domain/enums.ts and
frontend/lib/domain/errors.ts.
"""

from __future__ import annotations

from enum import StrEnum


class Priority(StrEnum):
    """frontend/lib/domain/enums.ts §14."""

    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    URGENT = "URGENT"


class ErrorCode(StrEnum):
    """Stable error codes (plan §28).

    The first four names are shared verbatim with the frontend's ERROR_CODE so
    no mapping layer is needed when the backend wires this up. The rest cover
    provider conditions the frontend mock never had to model.
    """

    # Shared with frontend/lib/domain/errors.ts §20.1
    AI_TIMEOUT = "AI_TIMEOUT"
    AI_PROVIDER_ERROR = "AI_PROVIDER_ERROR"
    AI_INVALID_JSON = "AI_INVALID_JSON"
    AI_SCHEMA_VALIDATION_FAILED = "AI_SCHEMA_VALIDATION_FAILED"

    # AI-service specific (plan §28)
    AI_PROVIDER_UNAVAILABLE = "AI_PROVIDER_UNAVAILABLE"
    AI_RATE_LIMITED = "AI_RATE_LIMITED"
    AI_NORMALIZATION_FAILED = "AI_NORMALIZATION_FAILED"
    AI_ESTIMATION_FAILED = "AI_ESTIMATION_FAILED"

    # Request-level
    EMPTY_DESCRIPTION = "EMPTY_DESCRIPTION"
    DESCRIPTION_TOO_LONG = "DESCRIPTION_TOO_LONG"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class WarningCode(StrEnum):
    """Non-fatal findings returned alongside a successful extraction (§16).

    A warning never fails the request: the manager reviews and overrides on the
    confirmation screen. Only a hard schema breach raises.
    """

    FIRING_TEMPERATURE_OUT_OF_RANGE = "FIRING_TEMPERATURE_OUT_OF_RANGE"
    QUANTITY_NOT_POSITIVE = "QUANTITY_NOT_POSITIVE"
    QUANTITY_IMPLAUSIBLE = "QUANTITY_IMPLAUSIBLE"
    DEADLINE_NOT_POSITIVE = "DEADLINE_NOT_POSITIVE"
    DEADLINE_IMPLAUSIBLE = "DEADLINE_IMPLAUSIBLE"
    DIMENSION_NOT_POSITIVE = "DIMENSION_NOT_POSITIVE"
    DIMENSION_IMPLAUSIBLE = "DIMENSION_IMPLAUSIBLE"

    AMBIGUOUS_QUANTITY = "AMBIGUOUS_QUANTITY"
    AMBIGUOUS_DEADLINE = "AMBIGUOUS_DEADLINE"
    AMBIGUOUS_DIMENSION = "AMBIGUOUS_DIMENSION"

    UNIT_CORRECTED = "UNIT_CORRECTED"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    ESTIMATE_UNAVAILABLE = "ESTIMATE_UNAVAILABLE"
    AI_PRIORITY_OVERRIDDEN = "AI_PRIORITY_OVERRIDDEN"
