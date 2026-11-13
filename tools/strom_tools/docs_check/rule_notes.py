"""Claude Code's rules files (`.claude/rules`): the globs of their `paths` and their text.

The hook after every Bash call reads them (`strom_tools.hooks.rules_loading`): this module imports no git."""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from strom_tools.docs_check.doc_lines import Context, Line, lines_of
from strom_tools.workspace.repository import Repository

RULES = ".claude/rules"
"""Claude Code's rules files: each loads when Claude touches a file its `paths` match (Read, Edit; for a Bash
command `strom_tools.hooks.rules_loading`), one without `paths` in every session."""
_GLOB_LINE = re.compile(r'\s*-\s+"?([^"\n]+?)"?\s*')
"""A line of the `paths` list in a rules file's front matter."""


@dataclass(frozen=True)
class RuleNote:
    """A rules file."""

    path: Path
    globs: list[str]
    """Of its `paths` front matter; none without one."""
    body: str
    """Without the front matter."""


def rule_notes(repository: Repository) -> list[RuleNote]:
    """The rules files, in the order of their names."""
    notes: list[RuleNote] = []
    for path in sorted((repository.root / RULES).glob("*.md")):
        lines = list(lines_of(path.read_text(encoding="utf-8")))
        notes.append(RuleNote(path, [glob for _, glob in globs_of(lines)], body_of(lines)))
    return notes


def body_of(lines: Iterable[Line]) -> str:
    """The text of a rules file without its front matter."""
    return "\n".join(line.text for line in lines if line.context is not Context.FRONT_MATTER).strip()


def globs_of(lines: Iterable[Line]) -> list[tuple[int, str]]:
    """The globs of a rules file's `paths`, each with its line number."""
    return [
        (line.number, match.expand(r"\1"))
        for line in lines
        if line.context is Context.FRONT_MATTER and (match := _GLOB_LINE.fullmatch(line.text)) is not None
    ]
