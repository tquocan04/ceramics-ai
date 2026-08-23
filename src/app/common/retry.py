"""Retry policy (plan §29).

Only transient faults are retried. A schema violation is a prompt/model
problem, not a network blip: retrying it burns latency and credits for the
same answer, so `retryable=False` short-circuits it.
"""

from __future__ import annotations

from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt, wait_exponential_jitter

from app.exceptions import ProviderError
from app.logging import get_logger

log = get_logger(__name__)


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, ProviderError) and exc.retryable


def _log_retry(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    log.warning(
        "llm.retry",
        attempt=state.attempt_number,
        error=type(exc).__name__ if exc else None,
        code=getattr(exc, "code", None),
    )


def build_retrying(max_retries: int) -> AsyncRetrying:
    """`max_retries` counts retries *after* the first attempt."""
    return AsyncRetrying(
        stop=stop_after_attempt(max_retries + 1),
        wait=wait_exponential_jitter(initial=0.5, max=4.0, jitter=0.5),
        retry=lambda state: bool(
            state.outcome
            and state.outcome.failed
            and _is_retryable(state.outcome.exception())
        ),
        before_sleep=_log_retry,
        reraise=True,
    )
