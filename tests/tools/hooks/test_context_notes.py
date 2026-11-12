from tool_helpers import commit, write

from strom_tools.hooks.context_notes import at_start
from strom_tools.hooks.hook_events import Session, SessionStarted
from strom_tools.hooks.hook_results import Note
from strom_tools.workspace.repository import Repository

SESSION = Session("abcd", None)


def test_after_a_summary_claude_gets_the_plans_and_the_changed_files(repository: Repository) -> None:
    write(repository, "docs/plans/shards.md", "# Shards\n\nScope: … Open: S2, X1.\n\nMore.\n")
    write(repository, "docs/plans/notes.md", "# Notes\n")
    write(repository, "src/kept.py")
    commit(repository)
    write(repository, "src/kept.py", "changed = 1\n")
    write(repository, "src/new.py")
    assert at_start(repository, SessionStarted(SESSION, "compact")) == Note(
        for_claude="After the summary: the state of the work.\n"
        "- plan `docs/plans/notes.md`\n"
        "- plan `docs/plans/shards.md`: Open: S2, X1.\n"
        "- uncommitted changes: src/kept.py, src/new.py"
    )


def test_without_plans_or_changes_it_says_so(repository: Repository) -> None:
    write(repository, "README.md")
    commit(repository)
    result = at_start(repository, SessionStarted(SESSION, "compact"))
    assert isinstance(result, Note) and result.for_claude is not None
    assert result.for_claude.splitlines()[1:] == ["- no plan in progress", "- no uncommitted changes"]


def test_only_a_summary_brings_the_note(repository: Repository) -> None:
    for source in ("startup", "clear", "resume"):
        assert at_start(repository, SessionStarted(SESSION, source)) is None
