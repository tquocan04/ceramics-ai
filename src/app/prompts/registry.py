"""Prompt registry (plan §24).

Prompts are versioned code. The version travels with every response and every
log line, so when extraction quality shifts you can tell which prompt produced
a given result.
"""

from __future__ import annotations

from app.features.order_extraction.prompt import ORDER_EXTRACTION_V2
from app.prompts.versions import PromptVersion

__all__ = ["ORDER_EXTRACTION_V2", "PromptVersion", "all_prompts", "get_prompt"]

_REGISTRY: dict[str, PromptVersion] = {
    ORDER_EXTRACTION_V2.name: ORDER_EXTRACTION_V2,
}


def get_prompt(name: str) -> PromptVersion:
    try:
        return _REGISTRY[name]
    except KeyError:  # pragma: no cover - programmer error
        raise KeyError(f"Unknown prompt version: {name}") from None


def all_prompts() -> dict[str, PromptVersion]:
    return dict(_REGISTRY)
