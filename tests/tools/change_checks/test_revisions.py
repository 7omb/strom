import os
from pathlib import Path

import pytest
from tool_helpers import commit, git, write

from strom_tools.change_checks.revisions import (
    Commit,
    Index,
    Revision,
    WorkingTree,
    _named,
    checkout,
    export,
    library_copy,
    parse,
    python_path_env,
)
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


@pytest.fixture
def three_states(repository: Repository) -> Repository:
    """A repository whose file `src/strom/__init__.py` says which state it is from: `committed`, `staged` or
    `working`; with a file only the index has (deleted since), an untracked and an ignored one."""
    write(repository, ".gitignore", "*.log\n")
    write(repository, "src/strom/__init__.py", "STATE = 'committed'\n")
    write(repository, "pyproject.toml", "")
    commit(repository)
    write(repository, "src/strom/__init__.py", "STATE = 'staged'\n")
    write(repository, "src/strom/staged_only.py", "")
    git(repository, "add", "src")
    (repository.root / "src/strom/staged_only.py").unlink()
    write(repository, "src/strom/__init__.py", "STATE = 'working'\n")
    write(repository, "src/strom/untracked.py", "")
    write(repository, "src/run.log", "")
    return repository


def files_in(directory: Path) -> list[str]:
    return sorted(path.relative_to(directory).as_posix() for path in directory.rglob("*") if path.is_file())


def test_parse_names_the_working_tree_the_index_and_commits(three_states: Repository) -> None:
    assert parse(three_states, ".") == WorkingTree()
    assert parse(three_states, ":index") == Index()
    assert parse(three_states, "HEAD") == Commit("HEAD")
    for revision in (".", ":index", "main"):
        assert _named(parse(three_states, revision)) == revision


def test_parse_rejects_what_is_no_commit(three_states: Repository) -> None:
    with pytest.raises(ToolError, match="no revision nowhere"):
        parse(three_states, "nowhere")
    tree = git(three_states, "rev-parse", "HEAD^{tree}")
    with pytest.raises(ToolError, match="no revision"):
        parse(three_states, tree)


@pytest.mark.parametrize(
    ("revision", "state", "files"),
    [
        (WorkingTree(), "working", ["src/strom/__init__.py", "src/strom/untracked.py"]),
        (Index(), "staged", ["src/strom/__init__.py", "src/strom/staged_only.py"]),
        (Commit("HEAD"), "committed", ["src/strom/__init__.py"]),
    ],
)
def test_export_writes_the_files_of_a_revision(
    three_states: Repository, tmp_path: Path, revision: Revision, state: str, files: list[str]
) -> None:
    export(three_states, revision, ["src"], tmp_path / "out")
    assert files_in(tmp_path / "out") == files
    assert (tmp_path / "out/src/strom/__init__.py").read_text() == f"STATE = '{state}'\n"


def test_checkout_exports_the_checked_paths_a_revision_has_and_links_the_venv(
    three_states: Repository, tmp_path: Path
) -> None:
    write(three_states, "tests/test_a.py", "")
    write(three_states, "docs/a.md", "")
    copy = checkout(three_states, WorkingTree(), tmp_path / "out")
    assert files_in(copy) == ["pyproject.toml", "src/strom/__init__.py", "src/strom/untracked.py", "tests/test_a.py"]
    assert (copy / ".venv").is_symlink() and os.readlink(copy / ".venv") == str(three_states.root / ".venv")
    assert files_in(checkout(three_states, Commit("HEAD"), tmp_path / "old")) == [
        "pyproject.toml",
        "src/strom/__init__.py",
    ]


def test_library_copy_is_what_import_strom_finds(three_states: Repository, tmp_path: Path) -> None:
    src = library_copy(three_states, Commit("HEAD"), tmp_path / "A")
    assert src == tmp_path / "A" / "src"
    assert (src / "strom/__init__.py").read_text() == "STATE = 'committed'\n"


def test_python_path_env_puts_the_copy_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/somewhere/else")
    assert python_path_env(tmp_path)["PYTHONPATH"] == f"{tmp_path}{os.pathsep}/somewhere/else"
    monkeypatch.delenv("PYTHONPATH")
    assert python_path_env(tmp_path)["PYTHONPATH"] == str(tmp_path)
