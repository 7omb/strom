from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from tool_helpers import write_transcript

from strom_tools.sessions.friction import (
    KINDS,
    Event,
    _call_of,
    _log_file,
    _logged,
    command_beginnings,
    events,
    last_logged,
    log_friction,
    log_retro,
    since_last_retro,
)
from strom_tools.workspace.repository import Repository

PAST, FUTURE = "2020-01-01T10:00:00.000Z", "2999-01-01T10:00:00.000Z"


def call(tool_id: str, name: str, at: str = PAST, **tool_input: object) -> dict[str, object]:
    block = {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}
    return {"type": "assistant", "timestamp": at, "message": {"content": [block]}}


def result(tool_id: str, text: str, *, is_error: bool = True, at: str = PAST) -> dict[str, object]:
    block = {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}
    return {"type": "user", "timestamp": at, "message": {"content": [block]}}


def said(text: str, at: str = PAST) -> dict[str, object]:
    return {"type": "user", "timestamp": at, "message": {"content": [{"type": "text", "text": text}]}}


def hook_block(tool_id: str, error: str, at: str = PAST) -> dict[str, object]:
    attachment = {"type": "hook_blocking_error", "toolUseID": tool_id, "hookName": "PostToolUse:Edit"}
    return {
        "type": "attachment",
        "timestamp": at,
        "attachment": {**attachment, "blockingError": {"blockingError": error}},
    }


REJECTION = "The user doesn't want to proceed with this tool use."
INTERRUPT = "[Request interrupted by user for tool use]"


def test_a_tool_use_is_named_by_its_tool_and_its_command_or_file() -> None:
    assert _call_of({"name": "Bash", "input": {"command": "make test"}}) == "Bash: make test"
    assert _call_of({"name": "Edit", "input": {"file_path": "/a.py", "old_string": "x"}}) == "Edit: /a.py"
    assert _call_of({"name": "Skill", "input": {"skill": "plan"}}) == "Skill: {'skill': 'plan'}"


def test_events_are_the_blocks_errors_rejections_interrupts_and_diagnostics(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            call("t1", "Edit", file_path="/a.py"),
            hook_block("t1", "ruff check after the edit"),
            hook_block("unknown", "at the stop"),
            call("t2", "Bash", command="make test"),
            result("t2", "Exit code 2"),
            result("t2", "fine", is_error=False),
            {"type": "attachment", "timestamp": PAST, "attachment": {"type": "diagnostics", "files": ["a.py"]}},
            call("t3", "Bash", command="rm -rf build"),
            result("t3", REJECTION),
            said("not that way"),
            call("t4", "Edit", file_path="/b.py"),  # Claude went on: t3 was rejected, not interrupted
            call("t5", "Edit", file_path="/c.py"),
            result("t4", REJECTION),
            result("t5", REJECTION),
            said(INTERRUPT),  # one interrupt cancelled both
            result("t5", "Permission for this tool was denied by the hook"),  # the session ends on a rejection
        ],
    )
    assert [(event.kind, event.call, event.answer) for event in events(path)] == [
        ("hook_blocks", "Edit: /a.py", "ruff check after the edit"),
        ("hook_blocks", "PostToolUse:Edit", "at the stop"),
        ("tool_errors", "Bash: make test", "Exit code 2"),
        ("diagnostics", "", '["a.py"]'),
        ("rejected", "Bash: rm -rf build", REJECTION),
        ("interrupts", "Edit: /b.py; Edit: /c.py", INTERRUPT),
        ("rejected", "Edit: /c.py", "Permission for this tool was denied by the hook"),
    ]
    assert events(path).__next__() == Event(PAST, "hook_blocks", "Edit: /a.py", "ruff check after the edit")


def test_events_since_a_time_leave_out_what_came_before(tmp_path: Path) -> None:
    old = [call("t1", "Bash", command="old"), result("t1", "failed")]
    new = [call("t2", "Bash", at=FUTURE, command="new"), result("t2", "failed too", at=FUTURE)]
    path = write_transcript(tmp_path / "session.jsonl", [*old, *new])
    since = datetime(2026, 1, 1, tzinfo=UTC)
    assert [event.call for event in events(path, since)] == ["Bash: new"]
    assert command_beginnings(path) == Counter({"old": 1, "new": 1})
    assert command_beginnings(path, since) == Counter({"new": 1})


def test_command_beginnings_are_the_first_two_words_of_bash_commands(tmp_path: Path) -> None:
    path = write_transcript(
        tmp_path / "session.jsonl",
        [
            call("t1", "Bash", command="git status --short"),
            call("t2", "Bash", command="git   status"),
            call("t3", "Bash", command="ls"),
            call("t4", "Edit", file_path="/a.py", command="git status"),
        ],
    )
    assert command_beginnings(path) == Counter({"git status": 2, "ls": 1})


def test_a_line_of_the_log_counts_what_a_session_added_since_its_last_line(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    assert _logged(repository) == [] and last_logged(repository) is None
    session = tmp_path / "abcd-1234.jsonl"
    before = [call("t1", "Bash", command="make"), result("t1", "failed"), hook_block("t1", "no")]
    write_transcript(session, before)
    log_friction(repository, session)
    resumed = [call("t2", "Bash", at=FUTURE, command="make"), result("t2", "again", at=FUTURE)]
    write_transcript(session, [*before, *resumed])
    log_friction(repository, session)
    first, second = _logged(repository)
    counts = {kind: 0 for kind in KINDS}
    assert {key: first[key] for key in ("session", *KINDS)} == {
        **counts,
        "session": "abcd-1234",
        "hook_blocks": 1,
        "tool_errors": 1,
    }
    assert {key: second[key] for key in ("session", *KINDS)} == {**counts, "session": "abcd-1234", "tool_errors": 1}
    assert _log_file(repository) == tmp_path / ".checks" / "friction.jsonl"


def test_a_retrospective_starts_the_count_anew(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    one, two = tmp_path / "one.jsonl", tmp_path / "two.jsonl"
    for session in (one, two):
        write_transcript(session, [call("t1", "Bash", command="make"), result("t1", "failed")])
    log_friction(repository, one)
    assert last_logged(repository) is None, "no retrospective yet"
    assert last_logged(repository, "one") is not None and last_logged(repository, "two") is None
    log_retro(repository)
    assert since_last_retro(repository) == []
    write_transcript(two, [call("t1", "Bash", at=FUTURE, command="make"), result("t1", "failed", at=FUTURE)])
    log_friction(repository, two)
    log_friction(repository, one)
    after = since_last_retro(repository)
    assert [(entry["session"], entry["tool_errors"]) for entry in after] == [("two", 1), ("one", 0)]
    retro_at = last_logged(repository)
    assert retro_at is not None and retro_at.tzinfo is not None
    assert [entry.get("retro") for entry in _logged(repository)] == [None, True, None, None]
