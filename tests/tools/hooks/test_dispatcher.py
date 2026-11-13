import io
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from tool_helpers import imported_after, make_calls, with_makefile, write

from strom_tools.hooks import dispatcher
from strom_tools.hooks.hook_events import Session, SessionEnded, SessionStarted, ToolRequested, ToolUsed, TurnEnded
from strom_tools.hooks.hook_results import Block, Failed, HookResult, Note
from strom_tools.workspace.repository import Repository

SESSION = Session("abcd", None)


def modules(handlers: Sequence[Callable[..., object]]) -> list[str]:
    return [handler.__module__.rsplit(".", 1)[1] for handler in handlers]


def test_every_event_has_its_handlers() -> None:
    assert modules(dispatcher._before_tool("Bash")) == ["command_guards"]
    assert [modules(dispatcher._after_tool(tool)) for tool in ["Edit", "MultiEdit", "Write", "Bash"]] == [
        ["python_fixes"],
        ["python_fixes"],
        ["python_fixes"],
        ["rules_loading"],
    ]
    assert (dispatcher._before_tool("Edit"), dispatcher._after_tool("Read")) == ([], [])
    assert modules(dispatcher._at_stop()) == ["python_fixes", "docs_fixes", "friction_notes"]
    assert modules(dispatcher._at_start()) == ["friction_notes", "rules_loading", "context_notes"]
    assert modules(dispatcher._at_end()) == ["friction_notes", "rules_loading"]


HANDLER_MODULES = {"command_guards", "context_notes", "docs_fixes", "friction_notes", "python_fixes", "rules_loading"}


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("", set[str]()),
        ("_before_tool('Bash')", {"command_guards"}),
        ("_before_tool('Edit')", set[str]()),
        ("_after_tool('Write')", {"python_fixes"}),
        ("_after_tool('Bash')", {"rules_loading"}),
        ("_after_tool('Read')", set[str]()),
        ("_at_stop()", {"python_fixes", "docs_fixes", "friction_notes"}),
        ("_at_start()", {"friction_notes", "rules_loading", "context_notes"}),
        ("_at_end()", {"friction_notes", "rules_loading"}),
    ],
)
def test_an_event_imports_only_the_modules_of_its_handlers(table: str, expected: set[str]) -> None:
    """The dispatcher imports no handler's module, and a table only those of its handlers."""
    imported = imported_after("from strom_tools.hooks import dispatcher", *([f"dispatcher.{table}"] if table else []))
    assert {name.removeprefix("strom_tools.hooks.") for name in imported} & HANDLER_MODULES == expected


def test_the_results_are_those_of_the_handlers_of_the_event(repository: Repository) -> None:
    with_makefile(repository)
    assert dispatcher._results(repository, ToolUsed(SESSION, "Read", "/a.py", None)) == []
    assert dispatcher._results(repository, ToolUsed(SESSION, "Bash", None, "ls")) == [None]
    assert dispatcher._results(repository, ToolRequested(SESSION, "Bash", "ls")) == [None]
    (refused,) = dispatcher._results(repository, ToolRequested(SESSION, "Bash", "git add -A"))
    assert isinstance(refused, Block)
    assert dispatcher._results(repository, ToolRequested(SESSION, "Edit", None)) == []
    assert dispatcher._results(repository, TurnEnded(SESSION, again=True)) == [None, None, None]
    assert dispatcher._results(repository, SessionStarted(SESSION, "resume")) == [None, None, None]
    assert dispatcher._results(repository, SessionEnded(SESSION)) == [None, None]
    edited = write(repository, "a.py")
    write(repository, "lint-python.fails", "an error\n")
    (result,) = dispatcher._results(repository, ToolUsed(SESSION, "Write", str(edited), None))
    assert isinstance(result, Block) and len(make_calls(repository)) == 2


def test_a_handler_that_raises_is_reported_and_the_others_still_run(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(repository: Repository, event: SessionStarted) -> HookResult:
        raise RuntimeError("out of order")

    def working(repository: Repository, event: SessionStarted) -> HookResult:
        return Note(for_user=f"started by {event.source}")

    monkeypatch.setattr(dispatcher, "_at_start", lambda: [broken, working])
    failed, noted = dispatcher._results(repository, SessionStarted(SESSION, "startup"))
    assert isinstance(failed, Failed)
    assert failed.message.startswith(f"hook {__name__}.broken failed:\nTraceback")
    assert failed.message.rstrip().endswith("RuntimeError: out of order")
    assert noted == Note(for_user="started by startup")


def run_main(payload: object, monkeypatch: pytest.MonkeyPatch, repository: Repository) -> int:
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(dispatcher, "this_repository", lambda: repository)
    return dispatcher.main()


def test_the_command_answers_with_the_exit_code_and_the_output(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with_makefile(repository)
    edited = write(repository, "a.py")
    write(repository, "lint-python.fails", "a.py:1:1: E501 Line too long\n")
    event = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": str(edited)}}
    assert run_main(event, monkeypatch, repository) == 2
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.startswith("ruff check after the edit:\na.py:1:1: E501 Line too long\n")

    write(repository, ".claude/rules/all.md", '---\npaths:\n  - "**"\n---\nA rule.\n')
    event = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "cat a.py"}}
    assert run_main(event, monkeypatch, repository) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and json.loads(captured.out) == {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "Contents of .claude/rules/all.md:\n\nA rule.",
        }
    }


def test_the_command_ignores_events_without_handlers(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_main({"hook_event_name": "PreCompact"}, monkeypatch, repository) == 0
    assert run_main({"hook_event_name": "PostToolUse", "tool_name": "Read"}, monkeypatch, repository) == 0
    assert capsys.readouterr() == ("", "")
