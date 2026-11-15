from datetime import UTC, datetime
from pathlib import Path

from tool_helpers import api_answer, write_transcript

from strom_tools.hooks.friction_notes import (
    _HEAVY_SUBAGENT,
    _LARGE_CONTEXT,
    _MIN_SESSIONS,
    _THRESHOLDS,
    _suggestion,
    at_end,
    at_start,
    at_stop,
)
from strom_tools.hooks.hook_events import Session, SessionEnded, SessionStarted, TurnEnded
from strom_tools.hooks.hook_results import Note
from strom_tools.sessions.friction import Kind, SessionLogged, _append_log, _logged, log_retro
from strom_tools.workspace.repository import Repository

SUMMARY = {"type": "system", "subtype": "compact_boundary"}
STOPPED = {"type": "system", "subtype": "stop_hook_summary"}


def log_session(repository: Repository, session: str, counts: dict[Kind, int]) -> None:
    _append_log(repository, SessionLogged(datetime.now(UTC), session, {**dict.fromkeys(Kind, 0), **counts}))


def test_the_end_of_a_session_logs_its_friction(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    block = {"type": "attachment", "attachment": {"type": "hook_blocking_error", "blockingError": "no"}}
    session = Session("abcd", write_transcript(tmp_path / "abcd.jsonl", [block, block]))
    assert at_end(repository, SessionEnded(session)) is None
    logged = [
        (line.session, line.counts[Kind.HOOK_BLOCKS]) for line in _logged(repository) if isinstance(line, SessionLogged)
    ]
    assert logged == [("abcd", 2)]


def test_a_session_without_a_transcript_logs_nothing(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    assert at_end(repository, SessionEnded(Session("abcd", None))) is None
    assert at_end(repository, SessionEnded(Session("abcd", tmp_path / "no_such.jsonl"))) is None
    assert _logged(repository) == []


def test_a_new_session_suggests_a_retrospective_past_a_threshold(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    limit = _THRESHOLDS[Kind.REJECTED]
    log_session(repository, "before", {Kind.REJECTED: 10 * limit})
    log_retro(repository)
    for number in range(_MIN_SESSIONS):
        assert at_start(repository, SessionStarted(Session("new", None), "startup")) is None
        log_session(repository, f"s{number}", {Kind.REJECTED: limit if number == 0 else 0, Kind.HOOK_BLOCKS: 1})
    result = at_start(repository, SessionStarted(Session("new", None), "clear"))
    note = (
        f"Friction in the {_MIN_SESSIONS} sessions since the last retrospective: {limit} rejected. "
        "Consider running the skill `retro` (it proposes fixes to CLAUDE.md, .claude/ and bin/)."
    )
    assert result == Note(for_user=note, for_claude=note)
    assert at_start(repository, SessionStarted(Session("new", None), "resume")) is None, "no new session"


def test_a_retrospective_is_suggested_past_a_threshold_of_enough_sessions() -> None:
    def line(session: str, counts: dict[Kind, int]) -> SessionLogged:
        return SessionLogged(datetime.now(UTC), session, {**dict.fromkeys(Kind, 0), **counts})

    limit = _THRESHOLDS[Kind.INTERRUPTS]
    sessions = [line(f"s{number}", {Kind.INTERRUPTS: limit if number == 0 else 0}) for number in range(_MIN_SESSIONS)]
    note = _suggestion(sessions)
    assert isinstance(note, Note) and note.for_user is not None and f"{limit} interrupts." in note.for_user
    assert _suggestion(sessions[1:]) is None, "below the threshold"
    assert _suggestion([line("resumed", {Kind.INTERRUPTS: limit})] * _MIN_SESSIONS) is None, "one session"
    assert _suggestion([line("a", {Kind.DIAGNOSTICS: 1000})] * _MIN_SESSIONS) is None, "a kind without a threshold"


def test_a_stop_says_once_that_the_context_was_summarised(tmp_path: Path) -> None:
    repository = Repository(tmp_path)
    transcript = write_transcript(tmp_path / "abcd.jsonl", [SUMMARY, STOPPED, SUMMARY])
    result = at_stop(repository, TurnEnded(Session("abcd", transcript), again=False))
    assert isinstance(result, Note) and result.for_claude is None and result.for_user is not None
    assert result.for_user.startswith("Context summary no. 2 of this session (its transcript has 0 MB)")
    write_transcript(transcript, [SUMMARY, STOPPED, SUMMARY, STOPPED])
    assert at_stop(repository, TurnEnded(Session("abcd", transcript), again=False)) is None, "said at the last stop"
    assert at_stop(repository, TurnEnded(Session("abcd", None), again=False)) is None


def test_a_stop_says_once_per_session_that_the_context_is_large(tmp_path: Path) -> None:
    def answer(message_id: str, context: int) -> dict[str, object]:
        return api_answer(message_id, read=context - 2)

    repository = Repository(tmp_path)
    session = Session("abcd", tmp_path / "abcd.jsonl")
    write_transcript(tmp_path / "abcd.jsonl", [answer("m1", _LARGE_CONTEXT - 1)])
    assert at_stop(repository, TurnEnded(session, again=False)) is None
    write_transcript(tmp_path / "abcd.jsonl", [answer("m1", _LARGE_CONTEXT - 1), answer("m2", _LARGE_CONTEXT)])
    result = at_stop(repository, TurnEnded(session, again=False))
    assert isinstance(result, Note) and result.for_claude is None and result.for_user is not None
    assert result.for_user.startswith(f"The context of this session has {_LARGE_CONTEXT // 1000}k tokens")
    assert at_stop(repository, TurnEnded(session, again=False)) is None, "said before"
    other = Session("ef01", write_transcript(tmp_path / "ef01.jsonl", [answer("m1", _LARGE_CONTEXT)]))
    assert isinstance(at_stop(repository, TurnEnded(other, again=False)), Note), "a memo per session"
    at_end(repository, SessionEnded(session))
    assert isinstance(at_stop(repository, TurnEnded(session, again=False)), Note), "the end forgets it"


def test_a_stop_names_once_each_subagent_whose_run_weighed_much(tmp_path: Path) -> None:
    def run(agent_id: str, agent_type: str, weight: int) -> None:
        """The transcript of a subagent with one request of that weight (2 input tokens, the rest output)."""
        write_transcript(subagents / f"agent-{agent_id}.jsonl", [api_answer("m1", output=(weight - 2) // 5)])
        (subagents / f"agent-{agent_id}.meta.json").write_text(f'{{"agentType": "{agent_type}"}}', encoding="utf-8")

    repository = Repository(tmp_path)
    session = Session("abcdef0123", write_transcript(tmp_path / "abcdef0123.jsonl", []))
    subagents = tmp_path / "abcdef0123" / "subagents"
    subagents.mkdir(parents=True)
    run("a1", "researcher", _HEAVY_SUBAGENT - 5)
    assert at_stop(repository, TurnEnded(session, again=False)) is None
    run("a1", "researcher", _HEAVY_SUBAGENT + 2)
    result = at_stop(repository, TurnEnded(session, again=False))
    assert isinstance(result, Note) and result.for_claude is None and result.for_user is not None
    assert result.for_user.startswith("A run of the subagent `researcher` weighed 0.6M tokens in 1 requests")
    assert "bin/sessions.py tokens abcdef01" in result.for_user
    assert at_stop(repository, TurnEnded(session, again=False)) is None, "said before"
    run("a2", "reviewer", 2 * _HEAVY_SUBAGENT)
    again = at_stop(repository, TurnEnded(session, again=False))
    assert isinstance(again, Note) and again.for_user is not None
    assert "`reviewer` weighed 1.2M" in again.for_user and "researcher" not in again.for_user, "a memo per run"
    at_end(repository, SessionEnded(session))
    both = at_stop(repository, TurnEnded(session, again=False))
    assert isinstance(both, Note) and both.for_user is not None, "the end forgets them"
    assert "researcher" in both.for_user and "reviewer" in both.for_user
