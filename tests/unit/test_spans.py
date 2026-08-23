"""Span resolution must be exact or absent -- never approximate."""

from __future__ import annotations

import pytest

from app.features.order_extraction.spans import find_span, strip_diacritics

DESC = "Gấp: 350 đĩa gốm men nâu họa tiết chim hạc cao 4cm, nung 1300°C, cần xong trong 7 ngày."


@pytest.mark.parametrize(
    "evidence",
    ["350", "đĩa gốm", "men nâu", "họa tiết chim hạc", "cao 4cm", "1300°C", "7 ngày"],
)
def test_exact_snippets_round_trip(evidence: str) -> None:
    span = find_span(DESC, evidence)
    assert span is not None
    assert DESC[span[0] : span[1]] == evidence


def test_case_insensitive() -> None:
    span = find_span(DESC, "MEN NÂU")
    assert span is not None
    assert DESC[span[0] : span[1]].casefold() == "men nâu"


def test_whitespace_tolerant() -> None:
    """The model often re-spaces what it quotes."""
    span = find_span(DESC, "cao   4cm")
    assert span is not None
    assert DESC[span[0] : span[1]] == "cao 4cm"


def test_diacritic_insensitive_maps_back_to_original_offsets() -> None:
    """A quote stripped of tone marks still highlights the accented original."""
    span = find_span(DESC, "hoa tiet chim hac")
    assert span is not None
    assert DESC[span[0] : span[1]] == "họa tiết chim hạc"


def test_d_stroke_is_folded() -> None:
    span = find_span(DESC, "dia gom")
    assert span is not None
    assert DESC[span[0] : span[1]] == "đĩa gốm"


def test_missing_evidence_returns_none_rather_than_guessing() -> None:
    assert find_span(DESC, "men lam") is None
    assert find_span(DESC, "") is None
    assert find_span("", "350") is None


def test_index_map_is_aligned() -> None:
    folded, index_map = strip_diacritics(DESC)
    assert len(folded) == len(index_map)
    assert all(0 <= i < len(DESC) for i in index_map)
    # Folding is 1:1 for Vietnamese, so offsets survive unchanged.
    assert len(folded) == len(DESC)


def test_span_never_exceeds_bounds() -> None:
    tail = "7 ngày."
    span = find_span(DESC, tail)
    assert span is not None
    assert span[1] <= len(DESC)
