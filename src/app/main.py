"""FastAPI application factory.

Configuration is validated at import time so a bad `.env` fails the process
start rather than the first request (plan Phase 0: "startup config validation").
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.common.enums import ErrorCode
from app.common.responses import ErrorBody, ErrorResponse
from app.config import get_settings
from app.exceptions import AIServiceError
from app.logging import configure_logging, get_logger, request_id_var

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "service.start",
        provider=settings.ai_provider,
        model=settings.ai_model,
        base_url=settings.ai_base_url,
        environment=settings.environment,
    )
    yield
    log.info("service.stop")


def _error_response(
    status: int, code: ErrorCode, message: str, details: dict[str, object] | None = None
) -> JSONResponse:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details))
    return JSONResponse(status_code=status, content=body.model_dump(mode="json"))


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title="Ceramics AI Service",
        description=(
            "Natural-language order extraction for the ceramics manufacturing "
            "pipeline. This service interprets language; it never owns "
            "manufacturing state."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(AIServiceError)
    async def _handle_service_error(
        _request: Request, exc: AIServiceError
    ) -> JSONResponse:
        log.warning("request.failed", code=exc.code.value, message=exc.message)
        return _error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            400,
            ErrorCode.VALIDATION_FAILED,
            "Dữ liệu không hợp lệ.",
            {"errors": exc.errors()},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        # Never leak a traceback to the caller (§33).
        log.exception("request.unhandled", error=str(exc))
        return _error_response(
            500, ErrorCode.INTERNAL_ERROR, "Lỗi nội bộ của dịch vụ AI."
        )

    app.include_router(api_router)
    return app


app = create_app()
