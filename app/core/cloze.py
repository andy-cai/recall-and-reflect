"""Cloze deletion parsing and rendering.

Anki-style syntax:
    The quick brown {{c1::fox}} jumps over the lazy {{c2::dog}}.

Each {{cN::text}} marker produces one card. When rendering card N, all cN markers
are blanked; other markers show their text.
"""

import re
from dataclasses import dataclass

CLOZE_RE = re.compile(r"\{\{c(\d+)::(.+?)\}\}")


@dataclass
class ClozeCard:
    index: int
    question: str
    answer: str


def has_cloze(source: str) -> bool:
    return bool(CLOZE_RE.search(source or ""))


def extract_cloze_cards(source: str) -> list[ClozeCard]:
    """Parse a cloze source string and return one ClozeCard per unique cN index."""
    matches = CLOZE_RE.findall(source)
    if not matches:
        return []

    by_index: dict[int, list[str]] = {}
    for idx_s, text in matches:
        by_index.setdefault(int(idx_s), []).append(text)

    cards = []
    for idx in sorted(by_index):
        cards.append(ClozeCard(
            index=idx,
            question=_render(source, idx, reveal=False),
            answer=" / ".join(by_index[idx]),
        ))
    return cards


def _render(source: str, target_index: int, reveal: bool) -> str:
    def repl(match: re.Match) -> str:
        idx = int(match.group(1))
        text = match.group(2)
        if idx == target_index:
            return f"[{text}]" if reveal else "[ … ]"
        return text
    return CLOZE_RE.sub(repl, source)


def render_question(source: str, target_index: int) -> str:
    return _render(source, target_index, reveal=False)


def render_answer(source: str, target_index: int) -> str:
    return _render(source, target_index, reveal=True)
