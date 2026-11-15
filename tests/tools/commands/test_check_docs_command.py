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


def test_style_prints_the_counts_after_the_problems_and_keeps_the_exit_code(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fine = write(repository, "docs/fine.md", "One; two; three; four.\n")
    assert run_command(check_docs, [str(fine)], repository, monkeypatch) == 0
    assert capsys.readouterr().out == ""
    assert run_command(check_docs, ["--style", str(fine)], repository, monkeypatch) == 0
    assert capsys.readouterr().out == "docs/fine.md:1: 3 semicolons in a sentence: a list?\n"
    bad = write(repository, "docs/bad.md", "One; two; three; four `bin/nope.py`.\n")
    assert run_command(check_docs, ["--style", str(bad)], repository, monkeypatch) == 1
    problem, count = capsys.readouterr().out.splitlines()
    assert problem.startswith("docs/bad.md:1: bin/nope.py (not found")
    assert count == "docs/bad.md:1: 3 semicolons in a sentence: a list?"


def test_only_the_named_files_are_checked(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(repository, "docs/good.md", "Fine.\n")
    bad = write(repository, "docs/bad.md", "Run `bin/nope.py`.\n")
    assert run_command(check_docs, [str(good)], repository, monkeypatch) == 0
    assert run_command(check_docs, [str(good), str(bad)], repository, monkeypatch) == 1
    assert capsys.readouterr().out.count("\n") == 1
