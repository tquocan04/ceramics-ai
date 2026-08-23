"""Provider-agnostic result wrapper."""

from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel


@dataclass(slots=True)
class LLMResult[T: BaseModel]:
    """What every provider returns: the typed value plus call telemetry (§31)."""

    value: T
    provider: str
    model: str
    latency_ms: int = 0
    attempts: int = 1
    usage: dict[str, int] = field(default_factory=dict)
