"""Capture genuine model output for the replay fixture.

Run:  RUN_AI_INTEGRATION_TESTS=1 python -m tests.regression.record_live

This calls the real provider once per golden case and overwrites
`tests/fixtures/recorded/order_extraction_replay.json`, so the offline suite
afterwards replays what the model actually said rather than the seeded
approximation. Re-record whenever the prompt or the model changes -- and read
the diff, because it is the clearest view of how that change altered
behaviour.

Failures are recorded as `null` and skipped by the runner rather than aborting
the run, so one bad case does not cost you the other twenty-nine calls.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from app.config import get_settings
from app.features.order_extraction.prompt import ORDER_EXTRACTION_V2
from app.features.order_extraction.schemas import LLMOrderExtraction
from app.llm.client import PydanticAIProvider
from tests.regression.runner import load_cases
from tests.regression.seed_recordings import OUTPUT


async def record() -> dict[str, Any]:
    settings = get_settings()
    provider = PydanticAIProvider(settings)
    recordings: dict[str, Any] = {}

    for index, case in enumerate(load_cases(), start=1):
        print(f"[{index:>2}] {case.id} ... ", end="", flush=True)
        try:
            result = await provider.structured_output(
                instructions=ORDER_EXTRACTION_V2.instructions,
                user_input=case.description,
                output_type=LLMOrderExtraction,
                deadline_s=settings.ai_request_budget_seconds,
            )
        except Exception as exc:
            print(f"FAILED ({type(exc).__name__}: {exc})")
            recordings[case.id] = None
            continue

        recordings[case.id] = result.value.model_dump(mode="json")
        print(f"ok ({result.latency_ms} ms)")

    return recordings


def main() -> int:
    if os.getenv("RUN_AI_INTEGRATION_TESTS") != "1":
        print("Refusing to spend API credits: set RUN_AI_INTEGRATION_TESTS=1")
        return 1

    recordings = asyncio.run(record())
    captured = {k: v for k, v in recordings.items() if v is not None}

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(
            {
                "source": "live",
                "model": get_settings().ai_model,
                "prompt_version": ORDER_EXTRACTION_V2.name,
                "note": "Captured from the real provider by record_live.py.",
                "recordings": captured,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")

    failed = len(recordings) - len(captured)
    suffix = f" ({failed} failed)" if failed else ""
    print(f"\nwrote {len(captured)} recordings to {OUTPUT}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
