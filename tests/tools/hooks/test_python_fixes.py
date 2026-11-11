from pathlib import Path

from tool_helpers import commit, make_calls, with_makefile, write

from strom_tools.hooks.hook_events import Block, Session, ToolUsed, TurnEnded
from strom_tools.hooks.python_fixes import after_edit, at_stop
from strom_tools.workspace.repository import Repository

SESSION = Session("abcd", None)
IGNORED = "ARGS=--ignore F401,F811,F821,F822,F841"


def edit(path: Path) -> ToolUsed:
    return ToolUsed(SESSION, "Edit", str(path), None)


def test_an_edited_python_file_is_fixed_and_linted_without_the_rules_of_a_half_done_change(
    repository: Repository,
) -> None:
    with_makefile(repository)
    edited = write(repository, "src/a.py", "import os\n")
    assert after_edit(repository, edit(edited)) is None
    assert make_calls(repository) == [f"fix FILES={edited} {IGNORED}", f"lint-python FILES={edited} {IGNORED}"]


def test_what_ruff_reports_after_an_edit_blocks(repository: Repository) -> None:
    with_makefile(repository)
    edited = write(repository, "src/a.pyi", "")
    write(repository, "lint-python.fails", "src/a.pyi:1:1: E501 Line too long\n")
    result = after_edit(repository, edit(edited))
    assert isinstance(result, Block)
    assert result.message.startswith("ruff check after the edit:\nsrc/a.pyi:1:1: E501 Line too long\nmake: *** ")


def test_other_files_are_left_as_written(repository: Repository, tmp_path: Path) -> None:
    with_makefile(repository)
    write(repository, "lint-python.fails", "an error\n")
    outside = tmp_path / "probe.py"
    outside.write_text("assert True\n")
    for path in (write(repository, "docs/a.md"), repository.root / "src/deleted.py", outside):
        assert after_edit(repository, edit(path)) is None
    assert after_edit(repository, ToolUsed(SESSION, "Bash", None, "ls")) is None
    assert make_calls(repository) == []


def test_at_the_end_of_a_turn_every_changed_python_file_is_checked_with_all_rules(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "src/a.py", "")
    commit(repository)
    write(repository, "src/a.py", "changed = 1\n")
    write(repository, "tests/test_new.py", "")
    write(repository, "docs/changed.md", "")
    assert at_stop(repository, TurnEnded(SESSION, again=False)) is None
    files = "FILES=src/a.py tests/test_new.py"
    assert make_calls(repository) == [f"fix {files} ARGS=", f"lint-python {files} ARGS="]
    write(repository, "lint-python.fails", "src/a.py:1:1: F401 unused\n")
    result = at_stop(repository, TurnEnded(SESSION, again=False))
    assert isinstance(result, Block)
    assert result.message.startswith("ruff check in the changed files:\nsrc/a.py:1:1: F401 unused\n")


def test_a_stop_blocks_once_per_turn_and_not_without_changed_python_files(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "lint-python.fails", "an error\n")
    write(repository, "docs/changed.md", "")
    assert at_stop(repository, TurnEnded(SESSION, again=False)) is None, "no Python file changed"
    write(repository, "src/a.py", "")
    assert at_stop(repository, TurnEnded(SESSION, again=True)) is None, "it blocked this turn's stop before"
    assert make_calls(repository) == []
