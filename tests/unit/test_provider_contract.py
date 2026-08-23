"""Provider-layer behaviour, driven offline by `FunctionModel`.

`FakeProvider` implements the `LLMProvider` Protocol, which begins *after*
every bug this module guards against. It cannot see output mode, output
retries, the timeout wrapping `agent.run`, the reasoning setting, or the
provider-exception mapping. The whole suite stayed green through a production
outage caused by exactly those.

`FunctionModel` is a real `pydantic_ai.Model`: the agent graph, output-mode
negotiation, retry loop, validation and error mapping all run for real, with a
local function standing in for the socket.
"""

from __future__ import annotations

import time

import pytest
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.common.enums import ErrorCode
from app.config import Settings
from app.exceptions import (
    BudgetExhausted,
    InvalidModelOutput,
    ProviderError,
    ProviderTimeout,
    SchemaValidationFailed,
)
from app.features.order_extraction.schemas import LLMOrderExtraction
from app.llm.client import PydanticAIProvider

#: The literal payload that took the service down: `URGENT` unquoted. Kept
#: verbatim so this test fails if anyone reintroduces an enum to the schema.
BROKEN_JSON = '{"quantity":350,"ai_priority":URGENT}'
GOOD_JSON = '{"quantity":350,"product_name":"Đĩa gốm"}'

VALID_TOOL = "record_order"


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "ai_provider": "openai-compatible",
        "ai_api_key": "test-key",
        "ai_base_url": "https://example.test/v1",
        "ai_model": "test/model",
        "ai_output_mode": "tool",
        "_env_file": None,
    }
    return Settings(**(base | overrides))  # type: ignore[arg-type]


def _tool_response(info: AgentInfo, args: str) -> ModelResponse:
    name = info.output_tools[0].name if info.output_tools else VALID_TOOL
    return ModelResponse(parts=[ToolCallPart(name, args)])


def _provider(fn, **overrides: object) -> PydanticAIProvider:
    settings = _settings(**overrides)
    # `supports_thinking` must be claimed or `Model.prepare_request` strips the
    # unified `thinking` setting before it is ever serialised -- which is
    # precisely what happens on the plain OpenAI path against OpenRouter.
    return PydanticAIProvider(
        settings, model=FunctionModel(fn, profile={"supports_thinking": True})
    )


async def _extract(provider: PydanticAIProvider, **kwargs: object):
    return await provider.structured_output(
        instructions="extract", user_input="350 đĩa gốm", output_type=LLMOrderExtraction,
        **kwargs,  # type: ignore[arg-type]
    )


# ── Output retries: the fix for the reported failure ─────────────────────────


async def test_malformed_output_is_repaired_in_conversation() -> None:
    """The model is shown its own parse error and answers with one completion.

    This is the cheap retry that `retries=0` had disabled.
    """
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return _tool_response(info, BROKEN_JSON if len(calls) == 1 else GOOD_JSON)

    result = await _extract(_provider(respond, ai_output_retries=1))

    assert len(calls) == 2, "expected one in-conversation repair"
    assert result.attempts == 1, "the transport layer must not have re-run"
    assert result.value.quantity == 350


async def test_persistent_malformed_output_is_not_retried_by_tenacity() -> None:
    """The regression guard for the production incident.

    Before the fix: `retries=0` plus `retryable=True` meant three full
    inferences of ~31s each, all producing byte-identical broken JSON, against
    a 35s budget. Cost must now be bounded by the output-retry budget alone.
    """
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return _tool_response(info, BROKEN_JSON)

    with pytest.raises(InvalidModelOutput) as excinfo:
        await _extract(_provider(respond, ai_output_retries=1, ai_max_retries=2))

    assert len(calls) == 2, f"1 + ai_output_retries expected, got {len(calls)}"
    assert excinfo.value.code is ErrorCode.AI_INVALID_JSON
    assert excinfo.value.retryable is False


async def test_zero_output_retries_costs_exactly_one_call() -> None:
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return _tool_response(info, BROKEN_JSON)

    with pytest.raises(InvalidModelOutput):
        await _extract(_provider(respond, ai_output_retries=0, ai_max_retries=2))

    assert len(calls) == 1


# ── Transport faults still belong to tenacity ────────────────────────────────


async def test_transport_error_is_retried_by_tenacity() -> None:
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        if len(calls) == 1:
            raise ModelHTTPError(status_code=503, model_name="test/model")
        return _tool_response(info, GOOD_JSON)

    result = await _extract(_provider(respond, ai_max_retries=1))

    assert len(calls) == 2
    assert result.attempts == 2, "a transport fault is the transport layer's job"


async def test_budget_exhaustion_is_not_retried() -> None:
    """Retrying cannot create time; sleeping past a dead deadline just adds latency."""
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        return _tool_response(info, GOOD_JSON)

    with pytest.raises(BudgetExhausted) as excinfo:
        await _extract(_provider(respond, ai_max_retries=2), deadline_s=0.0)

    assert calls == []
    assert excinfo.value.retryable is False


async def test_run_budget_covers_output_retries() -> None:
    """The run timeout must bound the whole run, not one HTTP round-trip.

    With only a per-request timeout, enabling output retries silently doubles
    what a single attempt can cost.
    """

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        time.sleep(0.25)
        return _tool_response(info, BROKEN_JSON)

    started = time.perf_counter()
    with pytest.raises(ProviderTimeout):
        await _extract(
            _provider(
                respond,
                ai_output_retries=3,
                ai_max_retries=0,
                ai_timeout_seconds=0.4,
                ai_attempt_seconds=0.4,
                ai_request_budget_seconds=5.0,
            )
        )
    elapsed = time.perf_counter() - started
    assert elapsed < 1.2, f"run budget did not bound the retries ({elapsed:.2f}s)"


# ── Error classification ─────────────────────────────────────────────────────


async def test_schema_violation_maps_to_422_not_502() -> None:
    """Valid JSON that breaks the schema is our problem, not the network's.

    Before the cause-chain inspection, AI_SCHEMA_VALIDATION_FAILED was
    documented in the README but unreachable in production.
    """

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return _tool_response(info, '{"quantity":"rather a lot"}')

    with pytest.raises(SchemaValidationFailed) as excinfo:
        await _extract(_provider(respond, ai_output_retries=0))

    assert excinfo.value.code is ErrorCode.AI_SCHEMA_VALIDATION_FAILED
    assert excinfo.value.status_code == 422


async def test_text_instead_of_a_tool_call_is_reported_cleanly() -> None:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Chắc chắn rồi! Đây là kết quả...")])

    with pytest.raises(ProviderError) as excinfo:
        await _extract(_provider(respond, ai_output_retries=0))
    assert excinfo.value.status_code in (422, 502)


# ── Agent wiring ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("reasoning", "expected_thinking"),
    [("off", False), ("low", "low"), ("high", "high")],
)
async def test_reasoning_is_sent_as_the_unified_thinking_setting(
    reasoning: str, expected_thinking: object
) -> None:
    seen: dict[str, AgentInfo] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["info"] = info
        return _tool_response(info, GOOD_JSON)

    await _extract(_provider(respond, ai_reasoning=reasoning))
    # `prepare_request` moves `thinking` out of model_settings and onto the
    # request parameters -- but only when the profile claims support. On a
    # profile that does not, it is dropped entirely and never reaches the wire.
    assert seen["info"].model_request_parameters.thinking == expected_thinking


async def test_temperature_is_omitted_when_reasoning_is_requested() -> None:
    """Providers ignore temperature under reasoning; sending it only warns."""
    seen: dict[str, AgentInfo] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["info"] = info
        return _tool_response(info, GOOD_JSON)

    await _extract(_provider(respond, ai_reasoning="low"))
    assert "temperature" not in (seen["info"].model_settings or {})


async def test_temperature_is_sent_when_reasoning_is_off() -> None:
    seen: dict[str, AgentInfo] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["info"] = info
        return _tool_response(info, GOOD_JSON)

    await _extract(_provider(respond, ai_reasoning="off", ai_temperature=0.0))
    assert (seen["info"].model_settings or {}).get("temperature") == 0.0


def test_openrouter_base_url_selects_the_openrouter_model() -> None:
    """Required for reasoning control: routed through the plain OpenAI model,
    OpenRouter's profile is never consulted and `thinking` is dropped."""
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.models.openrouter import OpenRouterModel

    openrouter = PydanticAIProvider(
        _settings(ai_base_url="https://openrouter.ai/api/v1")
    )
    assert isinstance(openrouter._model, OpenRouterModel)
    assert openrouter._model.profile.get("supports_thinking") is True

    other = PydanticAIProvider(_settings(ai_base_url="https://api.openai.com/v1"))
    assert isinstance(other._model, OpenAIChatModel)


def test_explicit_native_overrides_an_unsupported_profile() -> None:
    """OpenRouter reports every unlisted vendor prefix as unsupported.

    Without the profile override, `NativeOutput` raises `UserError` locally --
    before any HTTP call -- for models whose gateway handles `response_format`
    perfectly well.
    """
    provider = PydanticAIProvider(
        _settings(
            ai_base_url="https://openrouter.ai/api/v1",
            ai_model="stealth/ox-alpha",
            ai_output_mode="native",
        )
    )
    assert provider._model.profile.get("supports_json_schema_output") is True
    assert provider._output_mode == "native"


def test_auto_mode_follows_the_profile() -> None:
    provider = PydanticAIProvider(
        _settings(
            ai_base_url="https://openrouter.ai/api/v1",
            ai_model="stealth/ox-alpha",
            ai_output_mode="auto",
        )
    )
    # Unlisted on OpenRouter -> profile says no -> tool calling, no UserError.
    assert provider._output_mode == "tool"


async def test_thinking_is_dropped_when_the_profile_does_not_support_it() -> None:
    """The failure mode that made reasoning unconfigurable in production.

    Routed through `OpenAIChatModel` against an OpenRouter base URL, the
    profile reports `supports_thinking=False` and `Model.prepare_request`
    removes the setting silently -- so `AI_REASONING=off` had no effect at all.
    """
    seen: dict[str, AgentInfo] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["info"] = info
        return _tool_response(info, GOOD_JSON)

    provider = PydanticAIProvider(
        _settings(ai_reasoning="off"),
        model=FunctionModel(respond, profile={"supports_thinking": False}),
    )
    await _extract(provider)
    assert "thinking" not in (seen["info"].model_settings or {})
    assert seen["info"].model_request_parameters.thinking is None


async def test_mandatory_reasoning_demotes_instead_of_failing() -> None:
    """Some endpoints reason unconditionally and reject `off` with a 400.

    Observed: "Reasoning is mandatory for this endpoint and cannot be
    disabled." Failing the customer's request over a knob the provider does
    not offer would be the wrong call; ask for the cheapest level instead.
    """
    calls: list[object] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(info.model_request_parameters.thinking)
        if len(calls) == 1:
            raise ModelHTTPError(
                status_code=400,
                model_name="test/model",
                body={"message": "Reasoning is mandatory for this endpoint "
                                 "and cannot be disabled."},
            )
        return _tool_response(info, GOOD_JSON)

    provider = _provider(respond, ai_reasoning="off", ai_max_retries=0)
    result = await _extract(provider)

    assert calls == [False, "minimal"], calls
    assert result.value.quantity == 350
    # Memoised: a second request must not re-pay for the discovery.
    await _extract(provider)
    assert calls[-1] == "minimal"
