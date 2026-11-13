"""The lines of a doc, each with the part it is in: front matter, a code block, the list under **Rejected**, or
prose."""

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum


class Context(Enum):
    """What part of a doc a line is in."""

    FRONT_MATTER = "front matter"
    CODE = "code"
    """A code block, with its fences."""
    REJECTED = "rejected"
    """The list under **Rejected**, up to the next heading: the alternatives cite old names on purpose."""
    PROSE = "prose"


@dataclass(frozen=True)
class Line:
    number: int
    text: str
    context: Context


def lines_of(text: str) -> Iterator[Line]:
    """The lines of a doc, each with its context."""
    lines = text.splitlines()
    in_front_matter = bool(lines) and lines[0] == "---"
    in_code_block = in_rejected = False
    for number, line in enumerate(lines, start=1):
        if in_front_matter:
            in_front_matter = number == 1 or line != "---"
            yield Line(number, line, Context.FRONT_MATTER)
            continue
        if line.lstrip().startswith("```"):
            in_code_block = not in_code_block
            yield Line(number, line, Context.CODE)
            continue
        if line.startswith("#"):
            in_rejected = False
        elif line.startswith("**Rejected**"):
            in_rejected = True
        context = Context.CODE if in_code_block else Context.REJECTED if in_rejected else Context.PROSE
        yield Line(number, line, context)
