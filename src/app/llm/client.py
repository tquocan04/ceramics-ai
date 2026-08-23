"""Provider implementations.

`PydanticAIProvider` is the only place `pydantic_ai` is imported for real work.
`FakeProvider` reproduces the four failure modes the frontend mock could inject
(frontend/lib/mock/db.ts `AIFailureMode`) so the §6.5 error branches are
exercised as real code paths rather than simulated states.
"""

from __future__ import annotations

import asyncio
import re
import time
import warnings
from collections.abc import Callable
from enum import StrEnum
from typing import Literal, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput, PromptedOutput, ToolOutput
from pydantic_ai.agent import AgentRunResult
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.openrouter import OpenRouterModel
from pydantic_ai.output import OutputSpec
from pydantic_ai.profiles import ModelProfile
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.providers.openrouter import OpenRouterProvider
from pydantic_ai.settings import ModelSettings

from app.common.enums import ErrorCode
from app.common.retry import build_retrying
from app.config import Settings
from app.exceptions import (
    BudgetExhausted,
    InvalidModelOutput,
    ProviderError,
    ProviderTimeout,
    SchemaValidationFailed,
)
from app.llm.errors import map_provider_exception
from app.llm.models import LLMResult
from app.logging import get_logger

T = TypeVar("T", bound=BaseModel)

OutputMode = Literal["native", "tool", "prompted"]

#: pydantic-ai's local guard, plus the wire rejections that mean the same.
_NATIVE_REJECTED = re.compile(
    r"native structured output|response_format|json_schema", re.IGNORECASE
)

#: Endpoints that reason unconditionally reject any attempt to disable it.
_REASONING_MANDATORY = re.compile(r"reasoning is mandatory", re.IGNORECASE)

_THINKING: dict[str, bool | str] = {
    "off": False,
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}

# The library warns once per *request* that temperature is ignored under
# reasoning. True, unactionable per request, and it drowns the log. Downgrade
# to once per process; `_model_settings` also stops sending temperature at all
# when reasoning was requested. Not `catch_warnings()`, which mutates global
# state and is unsafe across concurrent asyncio requests.
warnings.filterwarnings(
    "once",
    message="Sampling parameters .* are not supported when reasoning is enabled",
    category=UserWarning,
)

log = get_logger(__name__)


def _force_native_output(base: ModelProfile) -> ModelProfile:
    """Assert JSON-schema output for a model the profile table does not know.

    OpenRouter's `model_profile` maps only a handful of vendor prefixes; every
    other model falls through to `DEFAULT_PROFILE`, where
    `supports_json_schema_output` is False. pydantic-ai then refuses
    `NativeOutput` *locally*, before any HTTP call, for models whose gateway
    forwards `response_format` perfectly well. Setting AI_OUTPUT_MODE=native
    is the operator asserting otherwise; if the gateway disagrees, the runtime
    demotion below catches it after exactly one wasted call.
    """
    return {**base, "supports_json_schema_output": True}


class PydanticAIProvider:
    """OpenAI-compatible structured output via PydanticAI.

    Works against any OpenAI-shaped endpoint -- OpenRouter, Groq, Together,
    a local Ollama, or OpenAI itself -- selected purely by `AI_BASE_URL`.
    """

    def __init__(self, settings: Settings, *, model: Model | None = None) -> None:
        if settings.ai_api_key is None:  # pragma: no cover - guarded in Settings
            raise ValueError("AI_API_KEY is required for the openai-compatible provider")

        self.name: str = settings.ai_provider
        self.model = settings.ai_model
        self._settings = settings
        # `model` is injectable purely so the offline suite can drive the real
        # agent wiring with a FunctionModel. Nothing in production passes it.
        self._model: Model = model if model is not None else self._build_model(settings)
        self._output_mode: OutputMode = self._resolve_output_mode()
        # Mutable: demoted in place if the provider rejects `off`.
        self._reasoning: str = settings.ai_reasoning

    @staticmethod
    def _build_model(settings: Settings) -> Model:
        api_key = settings.ai_api_key.get_secret_value()  # type: ignore[union-attr]
        profile = _force_native_output if settings.ai_output_mode == "native" else None

        if "openrouter.ai" in settings.ai_base_url:
            # OpenRouterModel is the only class that renders the unified
            # `thinking` setting as extra_body["reasoning"]. Routed through the
            # plain OpenAIChatModel the OpenRouter profile is never consulted,
            # `supports_thinking` is False, and `Model.prepare_request` drops
            # `thinking` silently -- so reasoning tokens can never be turned
            # off. Verified against the installed package.
            return OpenRouterModel(
                settings.ai_model,
                provider=OpenRouterProvider(api_key=api_key),
                profile=profile,
            )
        return OpenAIChatModel(
            settings.ai_model,
            provider=OpenAIProvider(base_url=settings.ai_base_url, api_key=api_key),
            profile=profile,
        )

    def _resolve_output_mode(self) -> OutputMode:
        configured = self._settings.ai_output_mode
        if configured != "auto":
            return configured
        if self._model.profile.get("supports_json_schema_output", False):
            return "native"
        return "tool"

    def _output_spec(self, output_type: type[T], mode: OutputMode) -> OutputSpec[T]:
        strict = self._settings.ai_output_strict
        if mode == "native":
            return NativeOutput(output_type, name="order_extraction", strict=strict)
        if mode == "prompted":
            return PromptedOutput(output_type, name="order_extraction")
        return ToolOutput(output_type, name="record_order", strict=strict)

    def _model_settings(self, http_timeout: float) -> ModelSettings:
        reasoning = self._reasoning
        settings: ModelSettings = {
            "max_tokens": self._settings.ai_max_tokens,
            "timeout": http_timeout,
            # One output tool, one call. Some gateways otherwise emit a batch.
            "parallel_tool_calls": False,
        }
        if reasoning != "default":
            settings["thinking"] = _THINKING[reasoning]  # type: ignore[typeddict-item]
        if reasoning in ("default", "off"):
            # Under active reasoning every provider ignores temperature, so
            # sending it only earns a warning. Omit it instead of being told.
            settings["temperature"] = self._settings.ai_temperature
        return settings

    def build_agent(
        self,
        instructions: str,
        output_type: type[T],
        *,
        mode: OutputMode | None = None,
        http_timeout: float = 30.0,
    ) -> Agent[None, T]:
        """Public so the benchmark and the offline tests exercise exactly the
        agent production runs -- an agent assembled elsewhere measures a
        different program."""
        return Agent(
            self._model,
            output_type=self._output_spec(output_type, mode or self._output_mode),
            instructions=instructions,
            model_settings=self._model_settings(http_timeout),
            # The cheap retry lives here: the model is shown its own parse
            # error in the same conversation and answers with one short
            # completion. `tools: 0` because this agent has no function tools.
            retries={"tools": 0, "output": self._settings.ai_output_retries},
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

        async for attempt in build_retrying(
            self._settings.ai_max_retries, deadline_s=deadline_s
        ):
            with attempt:
                attempts += 1
                run = await self._run_with_fallback(
                    instructions,
                    user_input,
                    output_type,
                    self._remaining(started, deadline_s),
                )
                value = run.output
                run_usage = run.usage
                usage = {
                    "input_tokens": run_usage.input_tokens or 0,
                    "output_tokens": run_usage.output_tokens or 0,
                    "reasoning_tokens": (run_usage.details or {}).get(
                        "reasoning_tokens", 0
                    ),
                    "requests": run_usage.requests or 0,
                }

        latency_ms = int((time.perf_counter() - started) * 1000)
        log.info(
            "llm.call",
            provider=self.name,
            model=self.model,
            output_mode=self._output_mode,
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

    def _remaining(self, started: float, deadline_s: float | None) -> float:
        """Time this attempt may take: its own ceiling, or what is left."""
        budget = self._settings.ai_attempt_seconds
        if deadline_s is None:
            return budget
        remaining = deadline_s - (time.perf_counter() - started)
        if remaining <= 0:
            raise BudgetExhausted("Request budget exhausted before the call.")
        return min(budget, remaining)

    async def _run_with_fallback(
        self,
        instructions: str,
        user_input: str,
        output_type: type[T],
        run_budget: float,
    ) -> AgentRunResult[T]:
        try:
            return await self._run_once(
                instructions, user_input, output_type, self._output_mode, run_budget
            )
        except ProviderError as exc:
            message = str(exc)
            if _REASONING_MANDATORY.search(message) and self._reasoning == "off":
                # Some endpoints reason unconditionally and reject any attempt
                # to disable it ("Reasoning is mandatory for this endpoint and
                # cannot be disabled."). Asking for the cheapest level is the
                # nearest honourable thing to what the operator wanted, and it
                # beats failing a request over a knob the provider does not
                # offer. Memoised, so only the first request pays for it.
                log.warning(
                    "llm.reasoning_demoted",
                    model=self.model,
                    **{"from": "off", "to": "minimal"},
                )
                self._reasoning = "minimal"
                return await self._run_once(
                    instructions, user_input, output_type, self._output_mode, run_budget
                )

            if (
                self._settings.ai_output_mode_fallback
                and self._output_mode == "tool"
                and isinstance(exc, InvalidModelOutput)
                and exc.no_output
            ):
                # The model emitted no tool call at all. Some models advertise
                # `tools` and still cannot drive one: measured on
                # stealth/ox-alpha, tool calling scored 0/5 on a request that
                # prompted output answered 5/5. Asking for JSON in the prompt
                # is the remaining way to get the same data out of it.
                log.warning(
                    "llm.output_mode_demoted",
                    model=self.model,
                    **{"from": "tool", "to": "prompted"},
                )
                self._output_mode = "prompted"
                return await self._run_once(
                    instructions, user_input, output_type, "prompted", run_budget
                )

            rejected = _NATIVE_REJECTED.search(message)
            if not (
                self._settings.ai_output_mode_fallback
                and self._output_mode == "native"
                and rejected
            ):
                raise

        # Memoised: only the first request of the process pays for this.
        log.warning(
            "llm.output_mode_demoted", model=self.model, **{"from": "native", "to": "tool"}
        )
        self._output_mode = "tool"
        return await self._run_once(
            instructions, user_input, output_type, "tool", run_budget
        )

    async def _run_once(
        self,
        instructions: str,
        user_input: str,
        output_type: type[T],
        mode: OutputMode,
        run_budget: float,
    ) -> AgentRunResult[T]:
        # Two timeouts, two units of work: `timeout` guards one HTTP
        # round-trip, `asyncio.timeout` guards the whole run -- which now
        # contains 1 + ai_output_retries round-trips. With only the former, an
        # output retry silently doubles what an attempt costs.
        http_timeout = min(self._settings.ai_timeout_seconds, run_budget)
        agent = self.build_agent(
            instructions, output_type, mode=mode, http_timeout=http_timeout
        )
        try:
            async with asyncio.timeout(run_budget):
                return await agent.run(user_input)
        except TimeoutError as exc:
            raise ProviderTimeout(
                f"Attempt exceeded {run_budget:.1f}s for {self.model}."
            ) from exc
        except Exception as exc:
            raise map_provider_exception(exc, model=self.model) from exc


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
