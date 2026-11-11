import json
from pathlib import Path

from strom_tools.hooks.hook_events import (
    Answer,
    Block,
    Failed,
    HookEvent,
    Note,
    Session,
    SessionEnded,
    SessionStarted,
    ToolUsed,
    TurnEnded,
    _name_of,
    answer,
    parse,
)

SESSION = Session("abcd", Path("/transcripts/abcd.jsonl"))
BASE = {"session_id": "abcd", "transcript_path": "/transcripts/abcd.jsonl"}


def test_parse_makes_the_event_with_the_fields_the_handlers_use() -> None:
    edit = {**BASE, "hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": "/a.py"}}
    assert parse(edit) == ToolUsed(SESSION, "Edit", "/a.py", None)
    bash = {**BASE, "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert parse(bash) == ToolUsed(SESSION, "Bash", None, "ls")
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


def test_an_event_is_named_as_claude_code_names_it() -> None:
    events: list[HookEvent] = [
        ToolUsed(SESSION, "Edit", None, None),
        TurnEnded(SESSION, False),
        SessionStarted(SESSION, "startup"),
        SessionEnded(SESSION),
    ]
    assert [_name_of(event) for event in events] == ["PostToolUse", "Stop", "SessionStart", "SessionEnd"]


def test_nothing_to_say_is_an_empty_answer() -> None:
    assert answer(SessionEnded(SESSION), []) == Answer(0, "", "")
    assert answer(SessionEnded(SESSION), [None, None]) == Answer(0, "", "")


def test_blocks_go_to_stderr_with_exit_code_2() -> None:
    answered = answer(TurnEnded(SESSION, False), [Block("ruff: E501"), None, Block("docs: nope.py")])
    assert answered == Answer(2, "", "ruff: E501\ndocs: nope.py\n")


def test_a_failed_handler_is_reported_without_blocking() -> None:
    assert answer(TurnEnded(SESSION, False), [Failed("hook x failed"), None]) == Answer(1, "", "hook x failed\n")
    both = answer(TurnEnded(SESSION, False), [Failed("hook x failed"), Block("ruff: E501")])
    assert both == Answer(2, "", "hook x failed\nruff: E501\n")


def test_notes_are_one_json_object() -> None:
    event = SessionStarted(SESSION, "startup")
    answered = answer(event, [Note(for_user="to the user", for_claude="to Claude"), Note(for_claude="more"), None])
    assert answered.exit_code == 0 and answered.stderr == ""
    assert json.loads(answered.stdout) == {
        "systemMessage": "to the user",
        "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "to Claude\n\nmore"},
    }
    only_user = answer(TurnEnded(SESSION, False), [Note(for_user="one"), Note(for_user="two")])
    assert json.loads(only_user.stdout) == {"systemMessage": "one\n\ntwo"}
    assert only_user.stdout.count("\n") == 1 and only_user.stdout.endswith("\n")


def test_a_note_beside_a_block_is_still_printed() -> None:
    answered = answer(TurnEnded(SESSION, False), [Block("ruff: E501"), Note(for_user="a summary")])
    assert (answered.exit_code, answered.stderr) == (2, "ruff: E501\n")
    assert json.loads(answered.stdout) == {"systemMessage": "a summary"}
