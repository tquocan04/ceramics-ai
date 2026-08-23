"""Provider implementations.

`PydanticAIProvider` is the only place `pydantic_ai` is imported for real work.
`FakeProvider` reproduces the four failure modes the frontend mock could inject
(frontend/lib/mock/db.ts `AIFailureMode`) so the §6.5 error branches are
exercised as real code paths rather than simulated states.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from enum import StrEnum
from typing import TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.common.enums import ErrorCode
from app.common.retry import build_retrying
from app.config import Settings
from app.exceptions import (
    ProviderError,
    ProviderTimeout,
    SchemaValidationFailed,
)
from app.llm.errors import map_provider_exception
from app.llm.models import LLMResult
from app.logging import get_logger

T = TypeVar("T", bound=BaseModel)

log = get_logger(__name__)


class PydanticAIProvider:
    """OpenAI-compatible structured output via PydanticAI.

    Works against any OpenAI-shaped endpoint -- OpenRouter, Groq, Together,
    a local Ollama, or OpenAI itself -- selected purely by `AI_BASE_URL`.
    """

    def __init__(self, settings: Settings) -> None:
        if settings.ai_api_key is None:  # pragma: no cover - guarded in Settings
            raise ValueError("AI_API_KEY is required for the openai-compatible provider")

        self.name: str = settings.ai_provider
        self.model = settings.ai_model
        self._settings = settings
        self._openai_provider = OpenAIProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key.get_secret_value(),
        )

    def _build_agent(
        self, instructions: str, output_type: type[T], timeout: float
    ) -> Agent[None, T]:
        model = OpenAIChatModel(self.model, provider=self._openai_provider)
        return Agent(
            model,
            output_type=output_type,
            instructions=instructions,
            model_settings=ModelSettings(
                temperature=self._settings.ai_temperature,
                max_tokens=self._settings.ai_max_tokens,
                timeout=timeout,
            ),
            # We do our own retrying in `common.retry` so the policy stays in
            # one place and covers transport faults too.
            retries=0,
        )

    async def structured_output(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        deadline_s: float | None = None,
    ) -> LLMResult[T]:
        started = time.perf_counter()
        attempts = 0
        usage: dict[str, int] = {}

        async for attempt in build_retrying(self._settings.ai_max_retries):
            with attempt:
                attempts += 1
                # Never let a single attempt outlive the caller's remaining
                # budget: the outer asyncio.timeout is authoritative, and this
                # keeps the two from fighting over who cancels first.
                elapsed = time.perf_counter() - started
                per_attempt = self._settings.ai_timeout_seconds
                if deadline_s is not None:
                    remaining = deadline_s - elapsed
                    if remaining <= 0:
                        raise ProviderTimeout("Request budget exhausted before the call.")
                    per_attempt = min(per_attempt, remaining)

                agent = self._build_agent(instructions, output_type, per_attempt)
                try:
                    run = await agent.run(user_input)
                except Exception as exc:
                    raise map_provider_exception(exc, model=self.model) from exc

                value = run.output
                run_usage = run.usage
                usage = {
                    "input_tokens": run_usage.input_tokens or 0,
                    "output_tokens": run_usage.output_tokens or 0,
                    "requests": run_usage.requests or 0,
                }

        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "llm.call",
            provider=self.name,
            model=self.model,
            attempts=attempts,
            latency_ms=latency_ms,
            **usage,
        )
        return LLMResult(
            value=value,
            provider=self.name,
            model=self.model,
            latency_ms=latency_ms,
            attempts=attempts,
            usage=usage,
        )


class FailureMode(StrEnum):
    """Mirrors the frontend mock's injectable AIFailureMode."""

    NONE = "NONE"
    TIMEOUT = "TIMEOUT"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_JSON = "INVALID_JSON"
    SCHEMA_INVALID = "SCHEMA_INVALID"


class FakeProvider:
    """Scripted provider for offline tests.

    `responder` receives the user input and returns the model object to hand
    back, so a test can vary output per input without a network call.
    """

    def __init__(
        self,
        responder: Callable[[str], BaseModel] | None = None,
        *,
        failure_mode: FailureMode = FailureMode.NONE,
        latency_ms: int = 0,
        name: str = "fake",
        model: str = "fake-model",
    ) -> None:
        self.name = name
        self.model = model
        self.responder = responder
        self.failure_mode = failure_mode
        self.latency_ms = latency_ms
        self.calls: list[str] = []

    async def structured_output(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        deadline_s: float | None = None,
    ) -> LLMResult[T]:
        self.calls.append(user_input)

        if self.failure_mode is FailureMode.TIMEOUT:
            raise ProviderTimeout("Fake provider timed out.")
        if self.failure_mode is FailureMode.PROVIDER_ERROR:
            raise map_provider_exception(
                RuntimeError("fake provider exploded"), model=self.model
            )
        if self.failure_mode is FailureMode.INVALID_JSON:
            # PydanticAI surfaces unparseable output as UnexpectedModelBehavior,
            # which maps to AI_INVALID_JSON.
            from pydantic_ai.exceptions import UnexpectedModelBehavior

            raise map_provider_exception(
                UnexpectedModelBehavior(
                    "Model wrapped its JSON in prose",
                    'Chắc chắn rồi! ```json { "quantity": 200, }```',
                ),
                model=self.model,
            )
        if self.failure_mode is FailureMode.SCHEMA_INVALID:
            raise SchemaValidationFailed(
                "Fake provider returned a payload that violates the schema.",
                details={"field": "quantity", "value": -5},
            )

        if self.latency_ms:
            await asyncio.sleep(self.latency_ms / 1000)

        if self.responder is None:
            # AI_PROVIDER=fake exists so /health and the error paths work with
            # no API key. There is deliberately no canned success payload: a
            # response unrelated to the input would look like a working
            # extraction and hide a misconfiguration.
            raise ProviderError(
                ErrorCode.AI_PROVIDER_ERROR,
                "AI_PROVIDER=fake has no scripted response. Set AI_PROVIDER="
                "openai-compatible with an AI_API_KEY to extract for real.",
                retryable=False,
            )

        value = self.responder(user_input)
        if not isinstance(value, output_type):
            raise SchemaValidationFailed(
                f"Fake responder returned {type(value).__name__}, expected "
                f"{output_type.__name__}"
            )

        return LLMResult(
            value=value,
            provider=self.name,
            model=self.model,
            latency_ms=self.latency_ms,
            attempts=1,
            usage={},
        )
