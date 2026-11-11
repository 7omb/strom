"""`Memo`: what a hook remembers from one call to the next, as lines in a file of the state directory.

A memo that was never written, or was forgotten, recalls no lines; `remembered_at` tells it from one written
without lines."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strom_tools.workspace.repository import Repository, state_dir


@dataclass(frozen=True)
class Memo:
    path: Path


def memo(repository: Repository, name: str) -> Memo:
    """The memo `name` (a path in the state directory, e.g. `rules-loaded/SESSION.txt`)."""
    return Memo(state_dir(repository) / name)


def recalled(memo: Memo) -> list[str]:
    return memo.path.read_text(encoding="utf-8").splitlines() if memo.path.exists() else []


def remembered_at(memo: Memo) -> float | None:
    """When the memo was last written (a time as `os.stat` gives it); None if it is not there."""
    return memo.path.stat().st_mtime if memo.path.exists() else None


def remember(memo: Memo, lines: Sequence[str]) -> None:
    memo.path.parent.mkdir(parents=True, exist_ok=True)
    memo.path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def forget(memo: Memo) -> None:
    memo.path.unlink(missing_ok=True)
