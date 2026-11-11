"""`collect_ids` and `typing_snapshot`: a snapshot saved and compared, and the comparison with a revision."""

from collections.abc import Sequence
from pathlib import Path

import pytest
from tool_helpers import commit, run_command, write

from strom_tools.commands import collect_ids, command_line, typing_snapshot
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


@pytest.fixture
def tested(repository: Repository) -> Repository:
    """A repository with one committed test and a second one that is not."""
    write(repository, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    write(repository, "tests/test_a.py", "def test_one() -> None: ...\n")
    commit(repository)
    write(repository, "tests/test_b.py", "def test_two() -> None: ...\n")
    return repository


def test_collected_ids_are_saved_and_compared(
    tested: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(ToolError, match=r"no snapshot \.checks/collect-ids-before\.txt"):
        run_command(collect_ids, ["diff"], tested, monkeypatch)
    assert run_command(collect_ids, ["save", "--", "-k", "one"], tested, monkeypatch) == 0
    assert capsys.readouterr().out == "1 IDs saved in .checks/collect-ids-before.txt\n"
    assert run_command(collect_ids, ["diff", "--", "-k", "one"], tested, monkeypatch) == 0
    assert capsys.readouterr().out == "1 IDs saved, 1 now: 0 removed, 0 added\n"
    assert run_command(collect_ids, ["diff"], tested, monkeypatch) == 1
    assert capsys.readouterr().out == "+ tests/test_b.py::test_two\n1 IDs saved, 2 now: 0 removed, 1 added\n"


def test_collected_ids_are_compared_with_those_of_a_revision(
    tested: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tested.root / "tests/test_a.py").unlink()
    assert run_command(collect_ids, ["diff", "--against", "HEAD"], tested, monkeypatch) == 1
    assert capsys.readouterr().out == (
        "- tests/test_a.py::test_one\n+ tests/test_b.py::test_two\n1 IDs in HEAD, 1 now: 1 removed, 1 added\n"
    )
    assert run_command(collect_ids, ["diff", "--against", "."], tested, monkeypatch) == 0
    with pytest.raises(ToolError, match="no revision nowhere"):
        run_command(collect_ids, ["diff", "--against", "nowhere"], tested, monkeypatch)


@pytest.fixture
def checked(tested: Repository, monkeypatch: pytest.MonkeyPatch) -> Repository:
    """A repository whose checkers report what the file `diagnostics` of the checked directory says, a line per
    diagnostic (no checker runs: their output is parsed in `test_typing_diagnostics.py`)."""

    def diagnostics(tools: Sequence[str], root: Path) -> list[str]:
        reported = (root / "src" / "diagnostics").read_text().splitlines()
        return [line for line in reported if line.split()[0] in tools]

    monkeypatch.setattr(typing_snapshot, "diagnostics", diagnostics)
    monkeypatch.setattr(command_line, "require_modules", lambda *names: None)
    write(tested, "src/diagnostics", "mypy a.py: error: old\nty a.py: error[rule]: kept\n")
    commit(tested)
    write(tested, "src/diagnostics", "mypy a.py: error: new\nty a.py: error[rule]: kept\npyright a.py: error[r]: new\n")
    return tested


def test_diagnostics_are_saved_and_compared(
    checked: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(typing_snapshot, ["save", "--name", "x"], checked, monkeypatch) == 0
    assert capsys.readouterr().out == "3 diagnostics saved in .checks/typing-x.txt\n"
    assert run_command(typing_snapshot, ["diff", "--name", "x"], checked, monkeypatch) == 0
    write(checked, "src/diagnostics", "ty a.py: error[rule]: kept\npyright a.py: error[r]: new\n")
    assert run_command(typing_snapshot, ["diff", "--name", "x"], checked, monkeypatch) == 1
    assert capsys.readouterr().out.endswith("- mypy a.py: error: new\n3 diagnostics saved, 2 now: 1 removed, 0 added\n")
    assert run_command(typing_snapshot, ["diff", "--name", "x", "--tools", "ty", "pyright"], checked, monkeypatch) == 0
    assert capsys.readouterr().out == "2 diagnostics saved, 2 now: 0 removed, 0 added\n", (
        "only the lines of those tools"
    )


def test_diagnostics_are_compared_with_those_of_a_revision(
    checked: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_command(typing_snapshot, ["diff", "--against", "HEAD"], checked, monkeypatch) == 1
    assert capsys.readouterr().out == (
        "- mypy a.py: error: old\n+ mypy a.py: error: new\n+ pyright a.py: error[r]: new\n"
        "2 diagnostics in HEAD, 3 now: 1 removed, 2 added\n"
    )
    assert run_command(typing_snapshot, ["diff", "--against", "HEAD", "--tools", "ty"], checked, monkeypatch) == 0
