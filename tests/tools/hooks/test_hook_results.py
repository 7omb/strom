import json
from pathlib import Path

from strom_tools.hooks.hook_events import HookEvent, Session, SessionEnded, SessionStarted, ToolUsed, TurnEnded
from strom_tools.hooks.hook_results import CONTEXT_LIMIT, Answer, Block, Failed, Note, _name_of, answer

SESSION = Session("abcd", Path("/transcripts/abcd.jsonl"))


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


def test_notes_over_the_limit_are_left_out_whole() -> None:
    half = "a" * (CONTEXT_LIMIT // 2)
    notes = [Note(for_user=half, for_claude=half), Note(for_user="b" * (CONTEXT_LIMIT // 2), for_claude=half + "b")]
    output = json.loads(answer(TurnEnded(SESSION, False), [*notes, Note(for_claude="c")]).stdout)
    for text in (output["systemMessage"], output["hookSpecificOutput"]["additionalContext"]):
        assert len(text) <= CONTEXT_LIMIT and text.startswith(f"{half}\n\n(a note of ") and "b" not in text
    assert output["hookSpecificOutput"]["additionalContext"].endswith("\n\nc"), "a later note that fits goes in"


def test_a_note_beside_a_block_is_still_printed() -> None:
    answered = answer(TurnEnded(SESSION, False), [Block("ruff: E501"), Note(for_user="a summary")])
    assert (answered.exit_code, answered.stderr) == (2, "ruff: E501\n")
    assert json.loads(answered.stdout) == {"systemMessage": "a summary"}
