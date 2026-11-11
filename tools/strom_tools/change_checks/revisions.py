"""Revisions of the repository to compare a change with, and their files in a directory of their own.

A revision is a commit, the working tree (`.`, uncommitted changes included) or the index (`:index`, the staged
changes: a state to compare later edits with, without a commit)."""

import os
import shutil
import sys
import tarfile
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace import git_files
from strom_tools.workspace.processes import run_checked
from strom_tools.workspace.repository import SOURCE_ROOTS, Repository

WORKING_TREE = "."
"""How a command names the working tree."""
INDEX = ":index"
"""How a command names the index."""
_CHECKED = ["src", "tests", "benchmarks", "examples", "bin", "tools", "pyproject.toml"]
"""The paths the type checkers and pytest read (`pyproject.toml`)."""


@dataclass(frozen=True)
class WorkingTree:
    pass


@dataclass(frozen=True)
class Index:
    pass


@dataclass(frozen=True)
class Commit:
    name: str
    """What git resolves to a commit: a hash, a branch, a tag, `HEAD~2`."""


type Revision = WorkingTree | Index | Commit


def parse(repository: Repository, text: str) -> Revision:
    """The revision a command's argument names; a `ToolError` if it is none of this repository."""
    if text == WORKING_TREE:
        return WorkingTree()
    if text == INDEX:
        return Index()
    if not git_files.is_commit(repository, text):
        raise ToolError(f"no revision {text}")
    return Commit(text)


def as_argument(revision: Revision) -> str:
    """The revision as a command's argument names it."""
    match revision:
        case WorkingTree():
            return WORKING_TREE
        case Index():
            return INDEX
        case Commit(name):
            return name


def export(repository: Repository, revision: Revision, paths: Sequence[str], dest: Path) -> None:
    """Writes the files under `paths` (from the root) of `revision` into `dest`. A commit must have every path.

    For the working tree, the files git sees: tracked ones and untracked ones that are not ignored."""
    dest.mkdir(parents=True, exist_ok=True)
    match revision:
        case WorkingTree():
            for name in git_files.seen(repository, *paths):
                (dest / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(repository.root / name, dest / name)
        case Index():
            git_files.checkout_index(repository, git_files.staged(repository, *paths), dest)
        case Commit(name):
            with tempfile.TemporaryDirectory() as tmp:
                archived = Path(tmp) / "archive.tar"
                git_files.archive(repository, name, paths, archived)
                with tarfile.open(archived) as tar:
                    tar.extractall(dest, filter="data")


def checkout(repository: Repository, revision: Revision, dest: Path) -> Path:
    """Exports the `_CHECKED` paths of `revision` (those it has) into `dest`, with the repository's venv linked as
    `.venv` (where `pyproject.toml` points pyright and ty); `dest`, to run the checkers or pytest in."""
    export(repository, revision, [path for path in _CHECKED if _has(repository, revision, path)], dest)
    (dest / ".venv").symlink_to(repository.root / ".venv")
    return dest


def _has(repository: Repository, revision: Revision, path: str) -> bool:
    match revision:
        case WorkingTree():
            return (repository.root / path).exists()
        case Index():
            return bool(git_files.staged(repository, path))
        case Commit(name):
            return git_files.commit_has(repository, name, path)


def library_copy(repository: Repository, revision: Revision, dest: Path) -> Path:
    """Exports the library's source root of `revision` into `dest`; its path, checked to be what `import strom`
    finds with it first on PYTHONPATH (see `python_path_env`), not the venv's editable install.

    The package is found without importing it: a copy with an injected bug may hang on import."""
    root = SOURCE_ROOTS["strom"]
    export(repository, revision, [root], dest)
    src = dest / root
    found = run_checked(
        [sys.executable, "-c", "import importlib.util; print(importlib.util.find_spec('strom').origin)"],
        cwd=dest,
        env=python_path_env(src),
    ).strip()
    if not Path(found).is_relative_to(src):
        raise ToolError(f"`import strom` finds {found}, not the copy of {as_argument(revision)} in {src}")
    return src


def python_path_env(src: Path) -> dict[str, str]:
    """The environment with `src` first on PYTHONPATH: it precedes the editable install's `.pth` entry."""
    return {**os.environ, "PYTHONPATH": os.pathsep.join(filter(None, [str(src), os.environ.get("PYTHONPATH")]))}
