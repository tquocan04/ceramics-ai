"""Structured logging (plan §31).

One log line per AI request carrying request_id / feature / provider / model /
prompt_version / latency / attempt / status. Secrets never reach a log record:
API keys are `SecretStr` and the raw customer description is truncated.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

#: Set by the request-id middleware; picked up automatically by every log call.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

_REDACTED = "***redacted***"
_SECRET_KEYS = frozenset(
    {"ai_api_key", "api_key", "internal_api_key", "authorization", "x-internal-api-key"}
)


def _add_request_id(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    rid = request_id_var.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    return event_dict


def _redact_secrets(
    _logger: Any, _method: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _SECRET_KEYS:
            event_dict[key] = _REDACTED
    return event_dict


def _force_utf8_stdout() -> None:
    """Make stdout safe for Vietnamese.

    A default Windows console is cp1252, which cannot encode 'ấ'. Since every
    order description this service handles is Vietnamese, logging one would
    raise UnicodeEncodeError and fail the request -- an encoding detail taking
    down the actual work. `errors="replace"` is the belt-and-braces part: a
    stream that still cannot encode a character degrades to '?' rather than
    raising.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # A detached or already-closed stream cannot be reconfigured; the
        # logger is not worth failing a request over.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def configure_logging(*, level: str = "INFO", json_output: bool = False) -> None:
    _force_utf8_stdout()
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_request_id,
            _redact_secrets,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]


def truncate(text: str, limit: int = 200) -> str:
    """Customer text is sensitive; log a prefix only (§31)."""
    return text if len(text) <= limit else text[:limit] + "…"
