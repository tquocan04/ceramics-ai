"""Order extraction endpoint (plan §9.2)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.common.responses import ErrorResponse
from app.dependencies import get_extraction_service, require_internal_api_key
from app.features.order_extraction.schemas import (
    OrderAnalysisResponse,
    OrderExtractionRequest,
)
from app.features.order_extraction.service import OrderExtractionService

router = APIRouter(
    prefix="/v1/orders",
    tags=["order-extraction"],
    dependencies=[Depends(require_internal_api_key)],
    responses={
        400: {"model": ErrorResponse, "description": "Invalid request"},
        401: {"model": ErrorResponse, "description": "Missing internal API key"},
        422: {"model": ErrorResponse, "description": "Model output failed the schema"},
        502: {"model": ErrorResponse, "description": "Provider error"},
        504: {"model": ErrorResponse, "description": "Provider timed out"},
    },
)


@router.post(
    "/extract",
    response_model=OrderAnalysisResponse,
    summary="Extract structured order data from a natural-language description",
)
async def extract_order(
    payload: OrderExtractionRequest,
    service: Annotated[OrderExtractionService, Depends(get_extraction_service)],
) -> OrderAnalysisResponse:
    """Turn free-text Vietnamese into typed, evidence-backed order data.

    The response is advisory: the caller reviews it, the user confirms it, and
    only then does the backend create anything. This service writes nothing.
    """
    return await service.extract(payload.description, language=payload.language)
