"""Golden-dataset regression (plan §38-§40, AI-080).

Two modes, because they answer different questions:

* **replay** (default, offline) -- recorded model output is driven through the
  real post-LLM pipeline. This is what runs in CI and on every `pytest`. It
  cannot tell you whether the model reads Vietnamese well, but it will catch
  the day someone changes a formula, a threshold, or a span rule.

* **live** (`-m live`, needs `RUN_AI_INTEGRATION_TESTS=1`) -- the same cases
  against the real provider. This is where extraction accuracy is measured.

Both share `runner.py`, so a case added once is scored by both.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings, get_settings
from app.features.order_extraction.schemas import LLMOrderExtraction
from app.features.order_extraction.service import OrderExtractionService
from app.llm.client import FakeProvider, PydanticAIProvider
from tests.regression.runner import (
    FIXTURES,
    Case,
    FieldOutcome,
    format_table,
    load_cases,
    score_case,
    summarise,
)

REPLAY_FILE = FIXTURES / "recorded" / "order_extraction_replay.json"
REPORT_FILE = Path(__file__).parent / "report.json"

#: Replay drives deterministic code, so anything below perfect is a real defect.
REPLAY_THRESHOLD = 1.0
#: Live runs against a model; the floor guards against a genuine regression
#: rather than asserting a number nobody has measured yet (plan §6 "Target").
LIVE_THRESHOLD = 0.85


def _load_replay() -> dict[str, Any]:
    with REPLAY_FILE.open(encoding="utf-8") as handle:
        return json.load(handle)["recordings"]


def _write_report(mode: str, summary: dict[str, Any]) -> None:
    REPORT_FILE.write_text(
        json.dumps({"mode": mode, **summary}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _settings() -> Settings:
    return Settings(ai_provider="fake", ai_api_key=None)


# ── Dataset hygiene ──────────────────────────────────────────────────────────


def test_dataset_meets_the_minimum_size() -> None:
    """Plan AI-080 requires at least 25 order cases."""
    assert len(load_cases()) >= 25


def test_case_ids_are_unique() -> None:
    ids = [case.id for case in load_cases()]
    assert len(ids) == len(set(ids))


def test_every_case_has_a_recording() -> None:
    recordings = _load_replay()
    missing = [c.id for c in load_cases() if c.id not in recordings]
    assert not missing, f"regenerate with `python -m tests.regression.seed_recordings`: {missing}"


def test_dataset_covers_the_required_categories() -> None:
    """Plan §39 lists the variations the suite must include."""
    tags = {tag for case in load_cases() for tag in case.tags}
    for required in ("numerals", "units", "deadline", "missing", "ambiguous", "noise"):
        assert required in tags, f"no case tagged {required!r}"


def test_anti_hallucination_cases_exist() -> None:
    """At least a few cases must assert that a field stays null."""
    null_assertions = sum(
        1
        for case in load_cases()
        for value in case.expected.values()
        if value is None
    )
    assert null_assertions >= 10


# ── Replay ───────────────────────────────────────────────────────────────────


@pytest.mark.regression
def test_replay_pipeline(capsys: pytest.CaptureFixture[str]) -> None:
    recordings = _load_replay()
    service = OrderExtractionService(FakeProvider(), _settings())

    outcomes: list[FieldOutcome] = []
    for case in load_cases():
        raw = LLMOrderExtraction.model_validate(recordings[case.id])
        response = service.assemble(
            raw, description=case.description, provider="replay", model="replay"
        )
        outcomes.extend(score_case(case, response))

    summary = summarise(outcomes)
    _write_report("replay", summary)
    with capsys.disabled():
        print(format_table(summary))

    assert summary["accuracy"] >= REPLAY_THRESHOLD, (
        "the deterministic pipeline changed behaviour:\n" + format_table(summary)
    )


@pytest.mark.regression
def test_replay_spans_are_always_exact() -> None:
    """A highlight must land on the characters it claims, in every case."""
    recordings = _load_replay()
    service = OrderExtractionService(FakeProvider(), _settings())

    for case in load_cases():
        raw = LLMOrderExtraction.model_validate(recordings[case.id])
        response = service.assemble(
            raw, description=case.description, provider="replay", model="replay"
        )
        for field, (start, end) in response.provenance.items():
            sliced = case.description[start:end]
            quoted = response.evidence[field]
            assert sliced.casefold() == quoted.casefold(), (
                f"{case.id}.{field}: span {start}:{end} gives {sliced!r}, "
                f"evidence says {quoted!r}"
            )


@pytest.mark.regression
def test_replay_never_estimates_without_inputs() -> None:
    """No quantity means no clay figure -- an invented one would look derived."""
    recordings = _load_replay()
    service = OrderExtractionService(FakeProvider(), _settings())

    for case in load_cases():
        raw = LLMOrderExtraction.model_validate(recordings[case.id])
        response = service.assemble(
            raw, description=case.description, provider="replay", model="replay"
        )
        if response.extracted.quantity is None:
            assert response.estimated.clay_kg is None, case.id
            assert response.estimated.glaze_kg is None, case.id
        if response.extracted.firing_temperature_c is None:
            assert response.estimated.firing_duration_hours is None, case.id


# ── Live ─────────────────────────────────────────────────────────────────────

_LIVE_ENABLED = os.getenv("RUN_AI_INTEGRATION_TESTS") == "1"


@pytest.mark.live
@pytest.mark.skipif(not _LIVE_ENABLED, reason="set RUN_AI_INTEGRATION_TESTS=1")
async def test_live_extraction_accuracy(capsys: pytest.CaptureFixture[str]) -> None:
    """Measure the real model against the golden dataset."""
    get_settings.cache_clear()
    settings = get_settings()
    service = OrderExtractionService(PydanticAIProvider(settings), settings)

    outcomes: list[FieldOutcome] = []
    failures: list[str] = []
    for case in load_cases():
        try:
            response = await service.extract(case.description)
        except Exception as exc:
            failures.append(f"{case.id}: {type(exc).__name__}: {exc}")
            continue
        outcomes.extend(score_case(case, response))

    summary = summarise(outcomes)
    summary["errored_cases"] = failures
    _write_report("live", summary)
    with capsys.disabled():
        print(format_table(summary))
        if failures:
            print("  errored cases:")
            for line in failures:
                print(f"    {line}")

    assert not failures, f"{len(failures)} cases failed outright"
    assert summary["accuracy"] >= LIVE_THRESHOLD, format_table(summary)


@pytest.mark.live
@pytest.mark.skipif(not _LIVE_ENABLED, reason="set RUN_AI_INTEGRATION_TESTS=1")
async def test_live_never_invents_missing_values() -> None:
    """Plan Scenario B/D: the model must leave unstated fields null."""
    get_settings.cache_clear()
    settings = get_settings()
    service = OrderExtractionService(PydanticAIProvider(settings), settings)

    strict: list[Case] = [
        c for c in load_cases() if "anti-hallucination" in c.tags
    ]
    assert strict, "no anti-hallucination cases tagged"

    for case in strict:
        response = await service.extract(case.description)
        extracted = response.extracted.model_dump()
        for name, expected in case.expected.items():
            if expected is None:
                assert extracted[name] is None, (
                    f"{case.id}: invented {name}={extracted[name]!r}"
                )
