"""The difference of two lists of lines, compared as multisets (test IDs, diagnostics), and the snapshots such
lists are saved in to compare a later state with."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository, state_dir


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


def snapshot(repository: Repository, kind: str, name: str) -> Path:
    """The file of the snapshot `name` of a kind of lines (`collect-ids`, `typing`), in the state directory."""
    return state_dir(repository) / f"{kind}-{name}.txt"


def save(snapshot: Path, lines: Sequence[str]) -> None:
    snapshot.parent.mkdir(exist_ok=True)
    snapshot.write_text("".join(f"{line}\n" for line in sorted(lines)))


def saved(repository: Repository, snapshot: Path) -> list[str]:
    """The lines of a snapshot; a `ToolError` if it was never saved."""
    if not snapshot.exists():
        raise ToolError(f"no snapshot {snapshot.relative_to(repository.root)}: run `save` with the same --name first")
    return snapshot.read_text().splitlines()
