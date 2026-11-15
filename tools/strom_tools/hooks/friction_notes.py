"""Logs each session's friction, suggests a retrospective when it piles up and says when a session outgrows its
context.

  `at_end`    appends the session's friction to the friction log (`strom_tools.sessions.friction`).
  `at_start`  sums the lines logged since the last retrospective; past a threshold (`_THRESHOLDS`, after at least
              `_MIN_SESSIONS`) it tells the user and Claude to run the skill `retro`.
  `at_stop`   tells the user that a new session starts smaller: once per summary of the session's context, and
              once when the context reaches `_LARGE_CONTEXT` tokens; and names, once each, the subagents of the
              session whose run weighed `_HEAVY_SUBAGENT` tokens or more."""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.hooks.hook_events import Session, SessionEnded, SessionStarted, TurnEnded
from strom_tools.hooks.hook_results import HookResult, Note
from strom_tools.hooks.memos import Memo, forget, memo, recalled, remember, remembered_at
from strom_tools.sessions import friction
from strom_tools.sessions.friction import Kind, SessionLogged
from strom_tools.sessions.token_usage import context, subagent_usage
from strom_tools.sessions.transcripts import summaries
from strom_tools.workspace.repository import Repository

_LARGE_CONTEXT = 250_000
"""Tokens of context from which `at_stop` suggests a new session: the sessions of 2026-11-14 with subagents had a
mean of 220k to 540k per request (`docs/decisions/subagents.md`)."""
_HEAVY_SUBAGENT = 600_000
"""Weighted tokens (`strom_tools.sessions.token_usage`) from which `at_stop` names a subagent's run: what a review
is expected to stay under, twice that of a research run (`docs/decisions/subagents.md`)."""
_MIN_SESSIONS = 3
_THRESHOLDS = {Kind.HOOK_BLOCKS: 40, Kind.TOOL_ERRORS: 25, Kind.REJECTED: 4, Kind.INTERRUPTS: 6}
"""Sums since the last retrospective; reaching any one suggests the next."""


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    transcript = event.session.transcript
    if transcript is not None and transcript.exists():
        friction.log_friction(repository, transcript)
    forget(_large_context_said(repository, event.session))
    forget(_heavy_subagents_said(repository, event.session))
    return None


def at_start(repository: Repository, event: SessionStarted) -> HookResult:
    if event.source not in ("startup", "clear"):
        return None
    return _suggestion(friction.since_last_retro(repository))


def _suggestion(logged: Sequence[SessionLogged]) -> HookResult:
    """A note to run the skill `retro`, if the sessions' lines since the last retrospective reach a threshold."""
    totals = {kind: sum(line.counts[kind] for line in logged) for kind in _THRESHOLDS}
    reached = [f"{totals[kind]} {kind.value}" for kind, limit in _THRESHOLDS.items() if totals[kind] >= limit]
    num_sessions = len({line.session for line in logged})
    if num_sessions < _MIN_SESSIONS or not reached:
        return None
    note = (
        f"Friction in the {num_sessions} sessions since the last retrospective: {', '.join(reached)}. "
        "Consider running the skill `retro` (it proposes fixes to CLAUDE.md, .claude/ and bin/)."
    )
    return Note(for_user=note, for_claude=note)


def at_stop(repository: Repository, event: TurnEnded) -> HookResult:
    transcript = event.session.transcript
    if transcript is None or not transcript.exists():
        return None
    said = [
        _about_context(repository, event.session, transcript),
        *_about_heavy_subagents(repository, event.session, transcript),
    ]
    told = [text for text in said if text is not None]
    return Note(for_user="\n\n".join(told)) if told else None


def _about_context(repository: Repository, session: Session, transcript: Path) -> str | None:
    """That the context was summarised since the last stop, or, once, that it is large."""
    num_summaries, num_new = summaries(transcript)
    if num_new:
        return (
            f"Context summary no. {num_summaries} of this session (its transcript has "
            f"{transcript.stat().st_size / 1e6:.0f} MB): Claude goes on from the summary and reads the docs "
            "again. A new session for the next task starts smaller; what is open is in the plan or review file."
        )
    size, said = context(transcript), _large_context_said(repository, session)
    if size < _LARGE_CONTEXT or remembered_at(said) is not None:
        return None
    remember(said, [])
    return (
        f"The context of this session has {size // 1000}k tokens, and every request sends it again. A new "
        "session for the next task starts smaller; what is open is in the plan or review file."
    )


def _about_heavy_subagents(repository: Repository, session: Session, transcript: Path) -> list[str]:
    """A text per subagent of the session whose run reached `_HEAVY_SUBAGENT` and was not named before."""
    said = _heavy_subagents_said(repository, session)
    named = recalled(said)
    heavy = [
        (name, tokens)
        for name, tokens in subagent_usage(transcript)
        if tokens.total >= _HEAVY_SUBAGENT and name not in named
    ]
    if heavy:
        remember(said, [*named, *(name for name, _ in heavy)])
    return [
        f"A run of the subagent `{tokens.conversation}` weighed {tokens.total / 1e6:.1f}M tokens in "
        f"{tokens.num_calls} requests, where a run is expected to stay under {_HEAVY_SUBAGENT / 1e6:.1f}M "
        f"(docs/decisions/subagents.md): `bin/sessions.py tokens {session.id[:8]}` shows what it read again."
        for _, tokens in heavy
    ]


def _large_context_said(repository: Repository, session: Session) -> Memo:
    """Written once `at_stop` has said that the session's context is large."""
    return memo(repository, f"large-context/{session.id}.txt")


def _heavy_subagents_said(repository: Repository, session: Session) -> Memo:
    """The transcript names of the subagents that `at_stop` named as heavy."""
    return memo(repository, f"heavy-subagents/{session.id}.txt")
