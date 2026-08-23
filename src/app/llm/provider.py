"""The provider seam (plan §22).

PydanticAI already abstracts over vendors, so why another Protocol? Because it
abstracts the *wrong axis* for us. `Agent` still performs real I/O, so feature
code written against it can only be tested with a network call or a monkeypatch.
This Protocol is narrower than `Agent` -- one method, no tools, no history --
which makes `FakeProvider` a dozen lines and lets every unit and regression
test run offline and deterministically.
"""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.llm.models import LLMResult

T = TypeVar("T", bound=BaseModel)


class LLMProvider(Protocol):
    """Turns a prompt into a validated Pydantic model, or raises ProviderError."""

    name: str
    model: str

    async def structured_output(
        self,
        *,
        instructions: str,
        user_input: str,
        output_type: type[T],
        deadline_s: float | None = None,
    ) -> LLMResult[T]:
        """Run one logical call, retries included.

        `deadline_s` is the time left in the caller's whole-request budget; the
        implementation must not exceed it. Raises `ProviderError` subclasses
        only -- never a raw provider exception.
        """
        ...
