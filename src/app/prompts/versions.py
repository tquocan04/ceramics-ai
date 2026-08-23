"""The prompt value type.

Kept separate from `registry.py` so feature modules can declare a prompt
without importing the registry that collects them.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["PromptVersion"]


@dataclass(frozen=True, slots=True)
class PromptVersion:
    #: Stable identifier, returned in every response and logged per call (§24).
    name: str
    instructions: str
