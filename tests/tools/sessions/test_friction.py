import json
import os
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tool_helpers import write_transcript

from strom_tools.sessions.friction import (
    Event,
    Kind,
    RetroLogged,
    SessionLogged,
    _call_of,
    _log_file,
    _logged,
    command_beginnings,
    counted,
    covered,
    events,
    last_logged,
    log_friction,
    log_retro,
    since_last_retro,
)
from strom_tools.sessions.transcripts import ToolUse, _transcripts_dir
from strom_tools.workspace.repository import Repository

PAST, FUTURE = "2020-01-01T10:00:00.000Z", "2999-01-01T10:00:00.000Z"
NONE = dict.fromkeys(Kind, 0)
"""The counts of a session without friction."""


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
    assert _call_of(ToolUse("t1", "Bash", "make test", None, "")) == "Bash: make test"
    assert _call_of(ToolUse("t2", "Edit", None, "/a.py", "")) == "Edit: /a.py"
    assert _call_of(ToolUse("t3", "Skill", None, None, "{'skill': 'plan'}")) == "Skill: {'skill': 'plan'}"


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
        (Kind.HOOK_BLOCKS, "Edit: /a.py", "ruff check after the edit"),
        (Kind.HOOK_BLOCKS, "PostToolUse:Edit", "at the stop"),
        (Kind.TOOL_ERRORS, "Bash: make test", "Exit code 2"),
        (Kind.DIAGNOSTICS, "", '["a.py"]'),
        (Kind.REJECTED, "Bash: rm -rf build", REJECTION),
        (Kind.INTERRUPTS, "Edit: /b.py; Edit: /c.py", INTERRUPT),
        (Kind.REJECTED, "Edit: /c.py", "Permission for this tool was denied by the hook"),
    ]
    first = Event(datetime.fromisoformat(PAST), Kind.HOOK_BLOCKS, "Edit: /a.py", "ruff check after the edit")
    assert events(path).__next__() == first


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
    assert isinstance(first, SessionLogged) and isinstance(second, SessionLogged)
    assert (first.session, first.counts) == ("abcd-1234", {**NONE, Kind.HOOK_BLOCKS: 1, Kind.TOOL_ERRORS: 1})
    assert (second.session, second.counts) == ("abcd-1234", {**NONE, Kind.TOOL_ERRORS: 1})
    assert _log_file(repository) == tmp_path / ".checks" / "friction.jsonl"


def test_the_log_is_one_json_object_per_line_and_a_line_that_is_none_is_left_out(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    session = write_transcript(tmp_path / "abcd.jsonl", [call("t1", "Bash", command="make"), result("t1", "no")])
    log_friction(repository, session)
    log_retro(repository)
    with _log_file(repository).open("a") as log:
        log.write('not json\n["a list"]\n{"at": "no time", "retro": true}\n{"at": "2026-11-01T10:00:00+00:00"}\n')
        log.write('{"at": "2026-11-01T10:00:00+00:00", "session": "old", "hook_blocks": "many"}\n')
    lines = [json.loads(line) for line in _log_file(repository).read_text().splitlines()[:2]]
    assert list(lines[0]) == ["at", "session", *(kind.value for kind in Kind)]
    assert (lines[0]["session"], lines[0]["tool_errors"], lines[1]["retro"]) == ("abcd", 1, True)
    logged = _logged(repository)
    assert [type(line) for line in logged] == [SessionLogged, RetroLogged, SessionLogged]
    assert logged[2] == SessionLogged(datetime(2026, 11, 1, 10, tzinfo=UTC), "old", NONE), "a count that is none: 0"


def test_counted_gives_every_kind() -> None:
    found = [
        Event(None, Kind.REJECTED, "", ""),
        Event(None, Kind.REJECTED, "", ""),
        Event(None, Kind.INTERRUPTS, "", ""),
    ]
    assert counted(found) == {**NONE, Kind.REJECTED: 2, Kind.INTERRUPTS: 1}


def test_a_report_covers_the_named_sessions_else_those_since_a_time_else_the_last_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "config"))
    repository = Repository(tmp_path / "repository")
    directory = _transcripts_dir(repository)
    directory.mkdir(parents=True)
    for number, name in enumerate(["aaaa", "bbbb", "cccc"]):
        write_transcript(directory / f"{name}.jsonl", [])
        os.utime(directory / f"{name}.jsonl", (1000 * (number + 1), 1000 * (number + 1)))

    def stems(prefixes: list[str], num_recent: int, since: datetime | None) -> list[str]:
        return [path.stem for path in covered(repository, prefixes, num_recent, since)]

    assert stems(["cc", "aa"], 1, None) == ["cccc", "aaaa"], "named: whatever else is given"
    assert stems([], 2, None) == ["bbbb", "cccc"]
    assert stems([], 1, datetime.fromtimestamp(1500, UTC)) == ["bbbb", "cccc"], "since the time, not the last one"


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
    assert [(line.session, line.counts[Kind.TOOL_ERRORS]) for line in after] == [("two", 1), ("one", 0)]
    retro_at = last_logged(repository)
    assert retro_at is not None and retro_at.tzinfo is not None
    assert [isinstance(line, RetroLogged) for line in _logged(repository)] == [False, True, False, False]
