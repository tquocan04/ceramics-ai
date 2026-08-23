"""Service exception hierarchy and its HTTP mapping (plan §28).

Every failure leaves the service as an `AIServiceError`, so the FastAPI
handlers never have to guess a status code or leak a stack trace.
"""

from __future__ import annotations

from typing import Any

from app.common.enums import ErrorCode

#: Vietnamese messages, matching the tone of the frontend's ERROR_MESSAGE_VI.
_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.AI_TIMEOUT: "AI không phản hồi kịp thời.",
    ErrorCode.AI_PROVIDER_ERROR: "Nhà cung cấp AI gặp sự cố.",
    ErrorCode.AI_INVALID_JSON: "AI trả về dữ liệu không phải JSON hợp lệ.",
    ErrorCode.AI_SCHEMA_VALIDATION_FAILED: "Kết quả AI không khớp schema yêu cầu.",
    ErrorCode.AI_PROVIDER_UNAVAILABLE: "Không kết nối được tới nhà cung cấp AI.",
    ErrorCode.AI_RATE_LIMITED: "Nhà cung cấp AI đang giới hạn tốc độ truy cập.",
    ErrorCode.AI_NORMALIZATION_FAILED: "Không chuẩn hoá được dữ liệu AI trả về.",
    ErrorCode.AI_ESTIMATION_FAILED: "Không tính được ước lượng nguyên vật liệu.",
    ErrorCode.EMPTY_DESCRIPTION: "Mô tả đơn hàng không được để trống.",
    ErrorCode.DESCRIPTION_TOO_LONG: "Mô tả đơn hàng quá dài.",
    ErrorCode.VALIDATION_FAILED: "Dữ liệu không hợp lệ.",
    ErrorCode.UNAUTHORIZED: "Yêu cầu không được xác thực.",
    ErrorCode.INTERNAL_ERROR: "Lỗi nội bộ của dịch vụ AI.",
}

#: Only these leave the service as a retryable signal to the caller.
_STATUS: dict[ErrorCode, int] = {
    ErrorCode.EMPTY_DESCRIPTION: 400,
    ErrorCode.DESCRIPTION_TOO_LONG: 400,
    ErrorCode.VALIDATION_FAILED: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.AI_SCHEMA_VALIDATION_FAILED: 422,
    ErrorCode.AI_RATE_LIMITED: 429,
    ErrorCode.AI_PROVIDER_ERROR: 502,
    ErrorCode.AI_INVALID_JSON: 502,
    ErrorCode.AI_NORMALIZATION_FAILED: 500,
    ErrorCode.AI_ESTIMATION_FAILED: 500,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.AI_PROVIDER_UNAVAILABLE: 503,
    ErrorCode.AI_TIMEOUT: 504,
}


class AIServiceError(Exception):
    """Base class for everything this service reports to its caller."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message or _MESSAGES.get(code, code.value)
        self.details = details
        super().__init__(self.message)

    @property
    def status_code(self) -> int:
        return _STATUS.get(self.code, 500)


class ProviderError(AIServiceError):
    """Raised by the LLM layer. `retryable` drives the tenacity predicate."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.retryable = retryable
        super().__init__(code, message, details=details)


class ProviderTimeout(ProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(ErrorCode.AI_TIMEOUT, message, retryable=True)


class ProviderUnavailable(ProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(ErrorCode.AI_PROVIDER_UNAVAILABLE, message, retryable=True)


class ProviderRateLimited(ProviderError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(ErrorCode.AI_RATE_LIMITED, message, retryable=True)


class InvalidModelOutput(ProviderError):
    """The model replied, but not with parseable JSON (§6.5)."""

    def __init__(self, message: str | None = None, *, raw: str | None = None) -> None:
        super().__init__(
            ErrorCode.AI_INVALID_JSON,
            message,
            retryable=True,
            details={"raw_response": raw[:1000]} if raw else None,
        )


class SchemaValidationFailed(ProviderError):
    """Parsed as JSON, but does not satisfy the schema. Not retryable (§29)."""

    def __init__(
        self, message: str | None = None, *, details: dict[str, Any] | None = None
    ) -> None:
        super().__init__(
            ErrorCode.AI_SCHEMA_VALIDATION_FAILED, message, retryable=False, details=details
        )
