"""The passages of a doc, its paragraphs and list items as one text each, and the sentences of such a text: what
the checks of a doc's prose read (`decision_form`, `prose_counts`)."""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from strom_tools.docs_check.doc_lines import Context, Line

SPAN = ""
"""What stands for a code span in a passage's text: one word, a private-use character that no prose holds."""
_SPAN = re.compile(r"`[^`\n]*`")
_ITEM = re.compile(r"(\s*)(?:-|\d+\.)\s+")
_SENTENCE_END = re.compile(r"[.!?](?=[\"')\]]*(?:\s|$))")
_ABBREVIATIONS = ("e.g.", "i.e.", "vs.", "cf.")


@dataclass(frozen=True)
class Passage:
    """A paragraph or a list item, as one text."""

    line: int
    """Where it starts."""
    text: str
    """Its lines joined by spaces, a list item without its marker, and `SPAN` for each code span: what a span
    holds is no prose (its dots end no sentence, its digits are no measurement), and it counts as one word."""
    context: Context
    is_item: bool
    indent: int
    """The columns in front of a list item's marker (0: an item of no other item); 0 for a paragraph."""


def passages_of(lines: Iterable[Line]) -> Iterator[Passage]:
    """The paragraphs and list items of a doc's prose and of its list under **Rejected**: no heading, table row,
    code block or front matter."""
    start: Line | None = None
    parts: list[str] = []
    is_item, indent = False, 0
    for line in lines:
        text = line.text.strip()
        item = _ITEM.match(line.text)
        outside = line.context in (Context.FRONT_MATTER, Context.CODE) or not text or text.startswith(("#", "|"))
        if start is not None and (outside or item is not None or line.context is not start.context):
            yield Passage(start.number, _SPAN.sub(SPAN, " ".join(parts)), start.context, is_item, indent)
            start = None
        if outside:
            continue
        if start is None:
            start, parts, is_item, indent = line, [], item is not None, len(item.group(1)) if item is not None else 0
        parts.append(line.text[item.end() :].strip() if item is not None else text)
    if start is not None:
        yield Passage(start.number, _SPAN.sub(SPAN, " ".join(parts)), start.context, is_item, indent)


def sentences_of(text: str) -> tuple[list[str], str]:
    """The sentences of a passage's text that end, and what follows the last of them (empty if nothing does). A
    sentence ends with `.`, `!` or `?` in front of a space or of the text's end, unless that ends an abbreviation."""
    ended: list[str] = []
    start = 0
    for end in _SENTENCE_END.finditer(text):
        sentence = text[start : end.end()].strip()
        if sentence.endswith(_ABBREVIATIONS):
            continue
        ended.append(sentence)
        start = end.end()
    return ended, text[start:].strip()
