"""Counts that prompt a look at a doc's prose, for a review of the docs (`bin/check_docs.py --style`): a run of
items in one sentence, a long parenthesis. No count says that a text is hard to read, so none is a problem of
`make lint` (`docs/decisions/decision-form.md`)."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from strom_tools.docs_check.doc_lines import Context, lines_of
from strom_tools.docs_check.passages import Passage, passages_of, sentences_of
from strom_tools.workspace.repository import Repository, shown


class CountKind(Enum):
    """What is counted, as its message says it, with the hint of what to look for."""

    SEMICOLONS = "semicolons in a sentence: a list?"
    PARENTHESIS_WORDS = "words in a parenthesis: the main point?"


LIMITS = {CountKind.SEMICOLONS: 2, CountKind.PARENTHESIS_WORDS: 12}
"""The most of each kind that is no count to look at."""
_PARENTHESIS = re.compile(r"\(([^()]*)\)")


@dataclass(frozen=True)
class Count:
    """A count over its limit in a paragraph or a list item."""

    doc: str
    """As messages show it."""
    line: int
    kind: CountKind
    value: int
    """The largest of its kind in the passage."""


def counts(repository: Repository, doc: Path) -> list[Count]:
    """The counts over their limits in a doc, in the order of its lines."""
    name = shown(repository, doc)
    passages = passages_of(lines_of(doc.read_text(encoding="utf-8")))
    return [count for passage in passages for count in _passage_counts(name, passage)]


def rendered(count: Count) -> str:
    """A count as `FILE:LINE: N ...`."""
    return f"{count.doc}:{count.line}: {count.value} {count.kind.value}"


def _passage_counts(doc: str, passage: Passage) -> Iterator[Count]:
    ended, rest = sentences_of(passage.text)
    # under **Rejected** a parenthesis holds the reason, which is the main point there
    parentheses = [] if passage.context is Context.REJECTED else _parenthesis_words(passage.text)
    found = {
        CountKind.SEMICOLONS: max(sentence.count(";") for sentence in [*ended, rest]),
        CountKind.PARENTHESIS_WORDS: max(parentheses, default=0),
    }
    for kind, value in found.items():
        if value > LIMITS[kind]:
            yield Count(doc, passage.line, kind, value)


def _parenthesis_words(text: str) -> Iterator[int]:
    """The number of words in each innermost parenthesis."""
    for match in _PARENTHESIS.finditer(text):
        inner: str = match.group(1)
        yield len(inner.split())
