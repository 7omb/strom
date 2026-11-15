"""The form of a decision (a doc in `DECISIONS`): it starts with a sentence that says what was chosen, a rejected
alternative has its reason, and its measurements stand in a table, not in a sentence.

Why this form: `docs/decisions/decision-form.md`."""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from strom_tools.docs_check.doc_lines import Context, Line
from strom_tools.docs_check.passages import Passage, passages_of, sentences_of

DECISIONS = "docs/decisions"
FIRST_SENTENCE_WORDS = 40
"""A code span counts as one word."""
NUMBERS_PER_SENTENCE = 6
"""Without dates, and without what a code span or a name holds (`3.14t`, `F401`)."""

_REASONED = re.compile(r"\)$|\): ")
"""A rejected alternative with its reason: `alternative (why)`, or `alternative (when, what): why`."""
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = r"\d+(?:[.,]\d+)*"
_ALONE = re.compile(rf"(?<![\w.]){_NUMBER}(?!\.?\w)")
"""A number that is no part of a name, of a version with letters or of a hash; one with its unit attached (`60ms`)
is none either."""
_SERIES = re.compile(rf"(?<![\w.]){_NUMBER}(?:\s?/\s?{_NUMBER})+(?!\.?\w)")
_ARROW = re.compile(rf"{_NUMBER}\S*\s*->\s*{_NUMBER}")


@dataclass(frozen=True)
class NoFirstSentence:
    """A decision that starts with no sentence: its first paragraph ends none (a fragment, or a list of them), or
    no prose stands in front of its list under **Rejected**."""

    doc: str
    """As messages show it."""
    line: int
    """Of that paragraph; 1 where there is none."""


@dataclass(frozen=True)
class LongFirstSentence:
    """A decision whose first sentence has more than `FIRST_SENTENCE_WORDS` words."""

    doc: str
    line: int
    words: int


@dataclass(frozen=True)
class UnreasonedRejection:
    """An alternative under **Rejected** that does not end with its reason in parentheses (`_REASONED`)."""

    doc: str
    line: int


@dataclass(frozen=True)
class NumberSeries:
    """Numbers separated by slashes in a paragraph or a list item: a reader pairs them by position. A fraction and
    two versions look the same (`1/3`, `3.13/3.14`): they go in words or into a code span."""

    doc: str
    line: int
    series: str
    """The first one."""


@dataclass(frozen=True)
class ManyNumbers:
    """A paragraph or a list item with a sentence of more than `NUMBERS_PER_SENTENCE` numbers."""

    doc: str
    line: int
    count: int
    """Of its sentence with the most."""


@dataclass(frozen=True)
class PlainArrow:
    """`->` between two numbers, where `→` marks before and after. A mapping of numbers looks the same
    (`1 -> 2`): it goes into a code span."""

    doc: str
    line: int


type FormProblem = NoFirstSentence | LongFirstSentence | UnreasonedRejection | NumberSeries | ManyNumbers | PlainArrow


def form_problems(doc: str, lines: Sequence[Line]) -> list[FormProblem]:
    """What is off the form in a decision with these lines, in their order."""
    passages = list(passages_of(lines))
    of_passages = [problem for passage in passages for problem in _passage_problems(doc, passage)]
    return [*_first_sentence_problems(doc, passages), *of_passages]


def _first_sentence_problems(doc: str, passages: Sequence[Passage]) -> list[FormProblem]:
    """The problem of where a decision starts: the first passage after its title, which is no passage."""
    if not passages or passages[0].context is not Context.PROSE:
        return [NoFirstSentence(doc, 1)]
    first = passages[0]
    ended, _ = sentences_of(first.text)
    if not ended:
        return [NoFirstSentence(doc, first.line)]
    words = len(ended[0].split())
    return [LongFirstSentence(doc, first.line, words)] if words > FIRST_SENTENCE_WORDS else []


def _passage_problems(doc: str, passage: Passage) -> Iterator[FormProblem]:
    """The problems of one passage but that of the first sentence."""
    is_alternative = passage.context is Context.REJECTED and passage.is_item and passage.indent == 0
    if is_alternative and not _REASONED.search(passage.text):
        yield UnreasonedRejection(doc, passage.line)
    text = _DATE.sub("", passage.text)
    series = _SERIES.search(text)
    if series is not None:
        found: str = series.group()
        yield NumberSeries(doc, passage.line, found)
    ended, rest = sentences_of(text)
    most = max(sum(1 for _ in _ALONE.finditer(sentence)) for sentence in [*ended, rest])
    if most > NUMBERS_PER_SENTENCE:
        yield ManyNumbers(doc, passage.line, most)
    if _ARROW.search(text):
        yield PlainArrow(doc, passage.line)
