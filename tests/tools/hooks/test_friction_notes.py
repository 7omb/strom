from pathlib import Path

from tool_helpers import write_transcript

from strom_tools.hooks.friction_notes import _MIN_SESSIONS, _THRESHOLDS, at_end, at_start, at_stop
from strom_tools.hooks.hook_events import Note, Session, SessionEnded, SessionStarted, TurnEnded
from strom_tools.sessions.friction import _append_log, _logged, log_retro
from strom_tools.workspace.repository import Repository

SUMMARY = {"type": "system", "subtype": "compact_boundary"}
STOPPED = {"type": "system", "subtype": "stop_hook_summary"}


def test_the_end_of_a_session_logs_its_friction(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    block = {"type": "attachment", "attachment": {"type": "hook_blocking_error", "blockingError": "no"}}
    session = Session("abcd", write_transcript(tmp_path / "abcd.jsonl", [block, block]))
    assert at_end(repository, SessionEnded(session)) is None
    assert [(entry["session"], entry["hook_blocks"]) for entry in _logged(repository)] == [("abcd", 2)]


def test_a_session_without_a_transcript_logs_nothing(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    assert at_end(repository, SessionEnded(Session("abcd", None))) is None
    assert at_end(repository, SessionEnded(Session("abcd", tmp_path / "no_such.jsonl"))) is None
    assert _logged(repository) == []


def test_a_new_session_suggests_a_retrospective_past_a_threshold(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    limit = _THRESHOLDS["rejected"]
    _append_log(repository, {"session": "before", "rejected": 10 * limit})
    log_retro(repository)
    for number in range(_MIN_SESSIONS):
        assert at_start(repository, SessionStarted(Session("new", None), "startup")) is None
        _append_log(repository, {"session": f"s{number}", "rejected": limit if number == 0 else 0, "hook_blocks": 1})
    result = at_start(repository, SessionStarted(Session("new", None), "clear"))
    note = (
        f"Friction in the {_MIN_SESSIONS} sessions since the last retrospective: {limit} rejected. "
        "Consider running the skill `retro` (it proposes fixes to CLAUDE.md, .claude/ and bin/)."
    )
    assert result == Note(for_user=note, for_claude=note)
    assert at_start(repository, SessionStarted(Session("new", None), "resume")) is None, "no new session"


def test_many_lines_of_one_session_are_one_session(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    for _ in range(_MIN_SESSIONS):
        _append_log(repository, {"session": "resumed", "interrupts": _THRESHOLDS["interrupts"]})
    assert at_start(repository, SessionStarted(Session("new", None), "startup")) is None


def test_a_stop_says_once_that_the_context_was_summarised(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    transcript = write_transcript(tmp_path / "abcd.jsonl", [SUMMARY, STOPPED, SUMMARY])
    result = at_stop(repository, TurnEnded(Session("abcd", transcript), again=False))
    assert isinstance(result, Note) and result.for_claude is None and result.for_user is not None
    assert result.for_user.startswith("Context summary no. 2 of this session (its transcript has 0 MB)")
    write_transcript(transcript, [SUMMARY, STOPPED, SUMMARY, STOPPED])
    assert at_stop(repository, TurnEnded(Session("abcd", transcript), again=False)) is None, "said at the last stop"
    assert at_stop(repository, TurnEnded(Session("abcd", None), again=False)) is None
