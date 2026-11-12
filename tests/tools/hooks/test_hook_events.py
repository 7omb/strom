from pathlib import Path

from strom_tools.hooks.hook_events import (
    Session,
    SessionEnded,
    SessionStarted,
    ToolRequested,
    ToolUsed,
    TurnEnded,
    parse,
)

SESSION = Session("abcd", Path("/transcripts/abcd.jsonl"))
BASE = {"session_id": "abcd", "transcript_path": "/transcripts/abcd.jsonl"}


def test_parse_makes_the_event_with_the_fields_the_handlers_use() -> None:
    edit = {**BASE, "hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}
    assert parse(edit) == ToolUsed(SESSION, "Edit", "/a.py", None)
    bash = {**BASE, "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert parse(bash) == ToolUsed(SESSION, "Bash", None, "ls")
    assert parse({**bash, "hook_event_name": "PreToolUse"}) == ToolRequested(SESSION, "Bash", "ls")
    assert parse({**BASE, "hook_event_name": "Stop", "stop_hook_active": True}) == TurnEnded(SESSION, again=True)
    assert parse({**BASE, "hook_event_name": "Stop"}) == TurnEnded(SESSION, again=False)
    assert parse({**BASE, "hook_event_name": "SessionStart", "source": "clear"}) == SessionStarted(SESSION, "clear")
    assert parse({**BASE, "hook_event_name": "SessionEnd"}) == SessionEnded(SESSION)


def test_parse_takes_what_is_not_as_expected_as_missing() -> None:
    unknown = Session("unknown", None)
    assert parse({"hook_event_name": "SessionEnd", "session_id": 7, "transcript_path": None}) == SessionEnded(unknown)
    odd = {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": ["a.py"], "command": 3}}
    assert parse(odd) == ToolUsed(unknown, "Edit", None, None)
    assert parse({"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": "ls"}) == ToolUsed(
        unknown, "Bash", None, None
    )
    assert parse({"hook_event_name": "Stop", "stop_hook_active": "yes"}) == TurnEnded(unknown, again=False)


def test_parse_knows_no_other_events() -> None:
    assert parse({**BASE, "hook_event_name": "PreCompact"}) is None
    assert parse({}) is None and parse("no object") is None and parse(None) is None
