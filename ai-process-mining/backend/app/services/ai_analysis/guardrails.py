"""Checks run on LLM text after it comes back.

These flag rather than block: a word list will never catch every causal claim and
will sometimes trip on a harmless "because". Showing the flag next to the answer lets
the reader judge, and the structural safeguards (fact ids, tool-only numbers) do the
heavy lifting.
"""
from __future__ import annotations

import re

CAUSAL_PATTERNS = [
    r"\bbecause\b", r"\bdue to\b", r"\bcaused by\b", r"\bresults? from\b", r"\bthe reason\b",
    r"\bunderstaffed\b", r"\bunderperform\w*", r"\blazy\b", r"\bincompeten\w*", r"\binefficient (?:staff|employee|person)\b",
]
_CAUSAL = re.compile("|".join(CAUSAL_PATTERNS), re.IGNORECASE)
_NUM = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")


def causal_language(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in _CAUSAL.finditer(text or "")})


def _norm_num(s: str) -> str:
    s = s.replace(",", "")
    try:
        f = float(s)
    except ValueError:
        return s
    return f"{f:.2f}".rstrip("0").rstrip(".")


def numbers_in(text: str) -> set[str]:
    return {_norm_num(m.group(0)) for m in _NUM.finditer(text or "")}


def unverified_numbers(answer: str, source_text: str) -> list[str]:
    """Numbers in the answer that do not appear (after rounding normalisation) in tool outputs."""
    src = numbers_in(source_text)
    # Accept 1-decimal roundings of source numbers as well.
    rounded = set()
    for s in src:
        try:
            f = float(s)
            rounded |= {f"{f:.1f}".rstrip("0").rstrip("."), f"{round(f):d}"}
        except ValueError:
            pass
    ok = src | rounded
    return sorted(n for n in numbers_in(answer) if n not in ok and len(n.replace(".", "")) > 1)
