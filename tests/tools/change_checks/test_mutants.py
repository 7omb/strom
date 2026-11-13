from pathlib import Path

import pytest
from tool_helpers import commit, git, write

from strom_tools.change_checks.mutants import (
    Bug,
    Patch,
    Replace,
    Trial,
    Verdict,
    _inject,
    ended,
    failed_tests,
    try_bug,
    verdict,
)
from strom_tools.change_checks.revisions import Commit, WorkingTree
from strom_tools.tool_error import ToolError
from strom_tools.workspace.processes import ProcessRun
from strom_tools.workspace.repository import Repository

PASSED = ProcessRun(0, "", "")


@pytest.mark.parametrize(
    ("trial", "expected"),
    [
        (Trial(PASSED, ProcessRun(1, "", "")), Verdict.CAUGHT),
        (Trial(PASSED, PASSED), Verdict.MISSED),
        (Trial(PASSED, ProcessRun(None, "", "")), Verdict.HUNG),
        (Trial(PASSED, ProcessRun(2, "", "")), Verdict.UNDECIDED),
        (Trial(ProcessRun(1, "", ""), None), Verdict.UNDECIDED),
        (Trial(ProcessRun(None, "", ""), None), Verdict.UNDECIDED),
    ],
)
def test_the_verdict_follows_from_the_two_runs(trial: Trial, expected: Verdict) -> None:
    assert verdict(trial) == expected


def test_a_run_ended_hung_or_with_its_exit_code_and_names_the_tests_that_failed() -> None:
    assert (ended(ProcessRun(None, "", "")), ended(ProcessRun(4, "", ""))) == ("hung", "exit code 4")
    stdout = "..F\nFAILED tests/a.py::test_one - assert 1\nERROR tests/b.py - ImportError\nfailed: 1\n"
    assert failed_tests(ProcessRun(1, stdout, "")) == [
        "FAILED tests/a.py::test_one - assert 1",
        "ERROR tests/b.py - ImportError",
    ]


@pytest.fixture
def doubling(repository: Repository) -> Repository:
    """A repository with a library of one function and a test of it."""
    write(repository, "src/strom/__init__.py", "def double(x: int) -> int:\n    return 2 * x\n")
    write(repository, "tests/test_double.py", "import strom\n\n\ndef test_double():\n    assert strom.double(2) == 4\n")
    write(repository, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    commit(repository)
    return repository


def test_inject_replaces_the_one_occurrence(doubling: Repository) -> None:
    _inject(doubling.root, Replace("src/strom/__init__.py", "2 * x", "3 * x"))
    assert (doubling.root / "src/strom/__init__.py").read_text() == "def double(x: int) -> int:\n    return 3 * x\n"


@pytest.mark.parametrize(("old", "times"), [("4 * x", 0), ("x", 2)])
def test_inject_refuses_a_text_that_does_not_occur_once(doubling: Repository, old: str, times: int) -> None:
    with pytest.raises(ToolError, match=rf"OLD occurs {times} times in src/strom/__init__.py, not once"):
        _inject(doubling.root, Replace("src/strom/__init__.py", old, "y"))
    assert "2 * x" in (doubling.root / "src/strom/__init__.py").read_text()


def test_inject_applies_a_patch(doubling: Repository, tmp_path: Path) -> None:
    write(doubling, "src/strom/__init__.py", "def double(x: int) -> int:\n    return 3 * x\n")
    patch = tmp_path / "bug.patch"
    patch.write_text(git(doubling, "diff") + "\n")
    git(doubling, "checkout", "--", "src")
    _inject(doubling.root, Patch(patch))
    assert "3 * x" in (doubling.root / "src/strom/__init__.py").read_text()


@pytest.mark.parametrize(
    ("bug", "expected"),
    [
        (Replace("src/strom/__init__.py", "2 * x", "3 * x"), Verdict.CAUGHT),
        (Replace("src/strom/__init__.py", "2 * x", "x + x"), Verdict.MISSED),
    ],
)
def test_a_bug_is_tried_in_a_copy(doubling: Repository, tmp_path: Path, bug: Bug, expected: Verdict) -> None:
    trial = try_bug(doubling, bug, WorkingTree(), ["-q"], 120, tmp_path / "copy")
    assert verdict(trial) == expected
    assert trial.clean.returncode == 0
    assert "2 * x" in (doubling.root / "src/strom/__init__.py").read_text(), "the repository is unchanged"
    assert not (doubling.root / ".pytest_cache").exists()


@pytest.mark.parametrize("name", ["README.md", "Makefile"])
def test_the_copy_holds_the_files_of_the_root_that_tests_read(doubling: Repository, tmp_path: Path, name: str) -> None:
    """The example of `README.md`, the targets of `make check`: without them, the tests fail without the bug."""
    write(doubling, name, "read by a test\n")
    write(
        doubling,
        "tests/test_root.py",
        f"from pathlib import Path\n\n\ndef test_root():\n    Path({name!r}).read_text()\n",
    )
    bug = Replace("src/strom/__init__.py", "2 * x", "3 * x")
    assert verdict(try_bug(doubling, bug, WorkingTree(), ["-q"], 120, tmp_path / "copy")) == Verdict.CAUGHT


@pytest.mark.parametrize("args", [["-x", "-n", "4"], ["-q", "--exitfirst", "-nauto"], ["-x", "--numprocesses=2"]])
def test_exitfirst_with_xdist_is_refused(doubling: Repository, tmp_path: Path, args: list[str]) -> None:
    bug = Replace("src/strom/__init__.py", "2 * x", "3 * x")
    with pytest.raises(ToolError, match="pytest-xdist ends with exit code 2 at the first failure"):
        try_bug(doubling, bug, WorkingTree(), args, 120, tmp_path / "copy")


def test_tests_that_fail_without_the_bug_give_no_verdict(doubling: Repository, tmp_path: Path) -> None:
    """The working tree's test fails; the committed one, taken with `tests_from`, passes."""
    write(doubling, "tests/test_double.py", "def test_double():\n    assert False\n")
    bug = Replace("src/strom/__init__.py", "2 * x", "3 * x")
    failing = try_bug(doubling, bug, WorkingTree(), ["-q"], 120, tmp_path / "copy")
    assert failing.mutant is None and failing.clean.returncode == 1
    assert verdict(failing) == Verdict.UNDECIDED
    assert verdict(try_bug(doubling, bug, Commit("HEAD"), ["-q"], 120, tmp_path / "old")) == Verdict.CAUGHT
