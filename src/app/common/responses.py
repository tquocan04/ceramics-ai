"""Shared response envelopes.

The error envelope deliberately mirrors the frontend's `ApiError`
(frontend/lib/domain/types.ts):

    { "error": { "code": "...", "message": "...", "details": {...} } }
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.common.enums import ErrorCode, WarningCode

SCHEMA_VERSION = "1.0"


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class AnalysisWarning(BaseModel):
    """A non-fatal finding (plan §16). Shown beside the field in review."""

    code: WarningCode
    field: str | None = None
    message: str


class RequestMetadata(BaseModel):
    latency_ms: int = 0
    attempts: int = 1
    usage: dict[str, int] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str
    version: str
    provider: str
    model: str
