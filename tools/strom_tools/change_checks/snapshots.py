"""Snapshots: lists of lines (test IDs, diagnostics) saved in the state directory, to compare a later state with."""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository, state_dir


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
