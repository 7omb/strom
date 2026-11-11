"""The difference of two lists of lines, compared as multisets (test IDs, diagnostics)."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class LineDiff:
    removed: list[str]
    """The lines that are no longer there, sorted (a line as often as it is missing)."""
    added: list[str]
    num_before: int
    num_now: int


def diff_lines(before: Sequence[str], current: Sequence[str]) -> LineDiff:
    then, now = Counter(before), Counter(current)
    return LineDiff(sorted((then - now).elements()), sorted((now - then).elements()), then.total(), now.total())


def differs(diff: LineDiff) -> bool:
    return bool(diff.removed or diff.added)


def rendered(diff: LineDiff, what: str, label: str) -> str:
    """The removed (`-`) and added (`+`) lines and a summary: `what` the lines are, `label` where the earlier ones
    come from (saved, in REV)."""
    lines = [f"- {line}" for line in diff.removed] + [f"+ {line}" for line in diff.added]
    summary = (
        f"{diff.num_before} {what} {label}, {diff.num_now} now: {len(diff.removed)} removed, {len(diff.added)} added"
    )
    return "\n".join([*lines, summary])
