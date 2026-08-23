"""Liveness endpoint (plan §9.1). Deliberately unauthenticated."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.responses import HealthResponse
from app.config import Settings, get_settings

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    settings: Annotated[Settings, Depends(get_settings)],
) -> HealthResponse:
    """Reports which provider/model the process is configured against.

    No provider call is made: this must stay green even when the LLM is down,
    so the backend can distinguish "AI service dead" from "provider dead".
    """
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version="0.1.0",
        provider=settings.ai_provider,
        model=settings.ai_model,
    )
