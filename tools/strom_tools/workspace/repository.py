"""`Repository`: a checkout of this project, and where the tools find its parts."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

SOURCE_ROOTS: Mapping[str, str] = {"strom": "src", "strom_tools": "tools"}
"""The directory (from the root) that holds each package: the library and the tools."""


@dataclass(frozen=True)
class Repository:
    root: Path


def this_repository() -> Repository:
    """The repository that holds this package."""
    return Repository(Path(__file__).resolve().parents[3])


def state_dir(repository: Repository) -> Path:
    """Where the tools keep their state (snapshots, the friction log, what the hooks remember): not versioned."""
    return repository.root / ".checks"


def shown(repository: Repository, path: Path) -> str:
    """`path` as messages show it: from the root, if it is inside the repository."""
    return str(path.relative_to(repository.root) if path.is_relative_to(repository.root) else path)
