import pytest
from tool_helpers import commit, run_command, write

from strom_tools.commands import check_docs
from strom_tools.workspace.repository import Repository


def test_the_docs_of_the_repository_are_checked(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repository, "bin/tool.py")
    write(repository, "README.md", "Run `bin/tool.py`.\n")
    commit(repository)
    assert run_command(check_docs, [], repository, monkeypatch) == 0
    assert capsys.readouterr().out == ""
    write(repository, "docs/new.md", "Run `bin/nope.py`.\n")
    assert run_command(check_docs, [], repository, monkeypatch) == 1
    assert capsys.readouterr().out.startswith("docs/new.md:1: bin/nope.py (not found")


def test_only_the_named_files_are_checked(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(repository, "docs/good.md", "Fine.\n")
    bad = write(repository, "docs/bad.md", "Run `bin/nope.py`.\n")
    assert run_command(check_docs, [str(good)], repository, monkeypatch) == 0
    assert run_command(check_docs, [str(good), str(bad)], repository, monkeypatch) == 1
    assert capsys.readouterr().out.count("\n") == 1
