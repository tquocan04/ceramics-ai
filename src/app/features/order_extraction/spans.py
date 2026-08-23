"""Resolve the model's quoted evidence into character offsets (§11).

The frontend highlights source text using `provenance: {field: [start, end]}`,
so those offsets must be exact. We never ask the model for them -- counting
characters is precisely what LLMs are unreliable at, and a wrong offset
produces a visibly wrong highlight. Instead the model quotes text and we locate
the quote ourselves, escalating through four strategies:

    1. exact substring
    2. case-insensitive
    3. whitespace-tolerant  ("cao  4 cm" vs "cao 4cm")
    4. diacritic-insensitive ("hoa tiet" vs "họa tiết")

If all four fail we omit the field and emit EVIDENCE_NOT_FOUND. A missing
highlight is a cosmetic gap; a fabricated one is a correctness bug.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["find_span", "strip_diacritics"]


def strip_diacritics(text: str) -> tuple[str, list[int]]:
    """Fold Vietnamese diacritics, returning the folded text and an index map.

    `index_map[i]` is the offset in `text` of the character that produced
    `folded[i]`, so a span found in folded space can be mapped back exactly.
    Decomposing with NFD and dropping combining marks keeps this 1:1 for
    Vietnamese, but the map makes the result correct regardless.
    """
    folded_chars: list[str] = []
    index_map: list[int] = []

    for original_index, char in enumerate(text):
        for decomposed in unicodedata.normalize("NFD", char):
            if unicodedata.combining(decomposed):
                continue
            # đ/Đ carry no combining mark; normalise them explicitly.
            if decomposed in ("đ", "Đ"):
                decomposed = "d" if decomposed == "đ" else "D"
            folded_chars.append(decomposed)
            index_map.append(original_index)

    return "".join(folded_chars), index_map


def _span_from_folded(
    start: int, end: int, index_map: list[int], text_len: int
) -> tuple[int, int] | None:
    """Map a [start, end) span in folded space back to original offsets."""
    if start >= len(index_map) or end <= start:
        return None
    origin_start = index_map[start]
    # `end` is exclusive: take the origin of the last included character and
    # extend past it, clamping to the end of the string.
    origin_last = index_map[min(end, len(index_map)) - 1]
    return origin_start, min(origin_last + 1, text_len)


def _whitespace_tolerant_search(needle: str, haystack: str) -> tuple[int, int] | None:
    """Match token-by-token, allowing any run of whitespace between tokens."""
    tokens = needle.split()
    if not tokens:
        return None
    pattern = r"\s+".join(re.escape(token) for token in tokens)
    match = re.search(pattern, haystack, re.IGNORECASE | re.UNICODE)
    return (match.start(), match.end()) if match else None


def find_span(description: str, evidence: str) -> tuple[int, int] | None:
    """Locate `evidence` in `description`. Returns None rather than guessing."""
    if not evidence or not description:
        return None

    needle = evidence.strip()
    if not needle:
        return None

    # 1. Exact.
    index = description.find(needle)
    if index != -1:
        return index, index + len(needle)

    # 2. Case-insensitive. casefold() can change length (e.g. 'ß' -> 'ss'),
    #    which would corrupt the offsets, so only trust it when it does not.
    lowered_haystack = description.casefold()
    lowered_needle = needle.casefold()
    if len(lowered_haystack) == len(description) and len(lowered_needle) == len(needle):
        index = lowered_haystack.find(lowered_needle)
        if index != -1:
            return index, index + len(needle)

    # 3. Whitespace-tolerant, case-insensitive.
    span = _whitespace_tolerant_search(needle, description)
    if span is not None:
        return span

    # 4. Diacritic-insensitive, via the index map.
    folded_haystack, index_map = strip_diacritics(description)
    folded_needle, _ = strip_diacritics(needle)
    folded_span = _whitespace_tolerant_search(folded_needle, folded_haystack)
    if folded_span is not None:
        return _span_from_folded(*folded_span, index_map, len(description))

    return None
