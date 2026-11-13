import os

from tool_helpers import make_calls, with_makefile, write

from strom_tools.docs_check.doc_problems import UNTRACKED
from strom_tools.hooks.docs_fixes import _formatted, _verdict, at_stop
from strom_tools.hooks.hook_events import Session, TurnEnded
from strom_tools.hooks.hook_results import Block, Note
from strom_tools.hooks.memos import remembered_at
from strom_tools.workspace.repository import Repository

STOP = TurnEnded(Session("abcd", None), again=False)
NEW_FILE = f"docs/a.md:3: tools/new.py{UNTRACKED}\n"
NEW_NAME = f"docs/a.md:4: strom_tools.new.name{UNTRACKED}\n"
"""Lines of the docs check about citations that only lack a `git add`."""


def formatted_at(repository: Repository) -> float:
    """When the docs were last formatted (they were)."""
    at = remembered_at(_formatted(repository))
    assert at is not None
    return at


def test_the_changed_docs_are_formatted_and_every_doc_is_checked(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "docs/a.md", "# A\n")
    write(repository, "README.md", "# Readme\n")
    write(repository, "src/a.py", "")
    assert at_stop(repository, STOP) is None
    assert make_calls(repository) == ["fix FILES=README.md docs/a.md ARGS=", "lint-docs FILES= ARGS="]
    assert remembered_at(_formatted(repository)) is not None


def test_a_doc_is_formatted_again_only_after_it_changed(repository: Repository) -> None:
    with_makefile(repository)
    doc = write(repository, "docs/a.md", "# A\n")
    write(repository, "docs/b.md", "# B\n")
    at_stop(repository, STOP)
    at_stop(repository, STOP)
    assert make_calls(repository)[1:] == ["lint-docs FILES= ARGS=", "lint-docs FILES= ARGS="], "nothing to format"
    later = formatted_at(repository) + 10
    os.utime(doc, (later, later))
    at_stop(repository, STOP)
    assert make_calls(repository)[3:] == ["fix FILES=docs/a.md ARGS=", "lint-docs FILES= ARGS="]


def test_what_the_formatter_or_the_check_report_blocks(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "docs/a.md", "# A\n")
    write(repository, "lint-docs.fails", "docs/a.md:3: bin/nope.py (not found)\n")
    result = at_stop(repository, STOP)
    assert isinstance(result, Block)
    assert result.message.startswith("the docs after this turn's changes:\ndocs/a.md:3: bin/nope.py (not found)\n")
    write(repository, "fix.fails", "mdformat failed\n")
    before = formatted_at(repository)
    os.utime(repository.root / "docs/a.md", (before + 10, before + 10))
    result = at_stop(repository, STOP)
    assert isinstance(result, Block) and "mdformat failed\n" in result.message and "bin/nope.py" in result.message
    assert formatted_at(repository) == before, "not formatted: the next stop tries again"


def test_a_stop_checks_nothing_without_changes_or_a_second_time(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "lint-docs.fails", "a problem\n")
    assert at_stop(repository, STOP) is None, "the working tree has no changes"
    write(repository, "docs/a.md", "# A\n")
    assert at_stop(repository, TurnEnded(Session("abcd", None), again=True)) is None
    assert make_calls(repository) == []


def test_a_citation_of_a_file_that_is_only_untracked_goes_to_the_user_and_blocks_nothing(
    repository: Repository,
) -> None:
    """Staging is the user's: Claude could not make the check pass."""
    with_makefile(repository)
    write(repository, "docs/a.md", "# A\n")
    write(repository, "lint-docs.fails", NEW_FILE + NEW_NAME)
    result = at_stop(repository, STOP)
    assert isinstance(result, Note) and result.for_claude is None and result.for_user is not None
    header, *references = result.for_user.splitlines()
    assert "`git add`" in header
    assert references == [NEW_FILE.strip(), NEW_NAME.strip()], "without make's line about the failed target"


def test_untracked_citations_are_told_once_until_they_change(repository: Repository) -> None:
    with_makefile(repository)
    write(repository, "docs/a.md", "# A\n")
    write(repository, "lint-docs.fails", NEW_FILE + NEW_NAME)
    assert isinstance(at_stop(repository, STOP), Note)
    assert at_stop(repository, STOP) is None, "told at the last stop"
    write(repository, "lint-docs.fails", NEW_NAME)
    told = at_stop(repository, STOP)
    assert isinstance(told, Note) and told.for_user is not None and told.for_user.splitlines()[1:] == [NEW_NAME.strip()]
    (repository.root / "lint-docs.fails").unlink()
    assert at_stop(repository, STOP) is None, "the user staged the file: the check passes"
    write(repository, "lint-docs.fails", NEW_NAME)
    assert isinstance(at_stop(repository, STOP), Note), "untracked anew"


MAKES_LINE = "make: *** [Makefile:9: lint-docs] Error 1\n"
NOT_FOUND = "docs/a.md:5: bin/nope.py (not found)\n"


def test_a_problem_other_than_an_untracked_citation_blocks_with_all_and_keeps_what_was_told() -> None:
    told = [NEW_NAME.strip()]
    result, told_now = _verdict("", NEW_FILE + NOT_FOUND + MAKES_LINE, told)
    assert isinstance(result, Block) and NEW_FILE in result.message and NOT_FOUND in result.message
    assert told_now == told
    result, told_now = _verdict("mdformat failed\n", NEW_FILE + MAKES_LINE, told)
    assert isinstance(result, Block) and result.message.startswith("the docs after this turn's changes:\nmdformat")
    assert told_now == told


def test_untracked_citations_alone_are_a_note_unless_told_before() -> None:
    result, told_now = _verdict("", NEW_FILE + NEW_NAME + MAKES_LINE, [NEW_FILE.strip()])
    assert isinstance(result, Note) and result.for_user is not None
    assert result.for_user.splitlines()[1:] == told_now == [NEW_FILE.strip(), NEW_NAME.strip()]
    assert _verdict("", NEW_FILE + MAKES_LINE, [NEW_FILE.strip()]) == (None, [NEW_FILE.strip()]), "told before"
    assert _verdict("", "", [NEW_FILE.strip()]) == (None, []), "none: the next ones are new"
