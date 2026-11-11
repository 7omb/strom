"""Logs each session's friction, suggests a retrospective when it piles up and says when a session outgrows its
context.

  `at_end`    appends the session's friction to the friction log (`strom_tools.sessions.friction`).
  `at_start`  sums the lines logged since the last retrospective; past a threshold (`_THRESHOLDS`, after at least
              `_MIN_SESSIONS`) it tells the user and Claude to run the skill `retro`.
  `at_stop`   tells the user, once per summary of the session's context, that a new session starts smaller."""

from strom_tools.hooks.hook_events import HookResult, Note, SessionEnded, SessionStarted, TurnEnded
from strom_tools.sessions import friction
from strom_tools.sessions.transcripts import summaries
from strom_tools.workspace.repository import Repository

_MIN_SESSIONS = 3
_THRESHOLDS = {"hook_blocks": 40, "tool_errors": 25, "rejected": 4, "interrupts": 6}
"""Sums since the last retrospective; reaching any one suggests the next."""


def at_end(repository: Repository, event: SessionEnded) -> HookResult:
    transcript = event.session.transcript
    if transcript is not None and transcript.exists():
        friction.log_friction(repository, transcript)
    return None


def at_start(repository: Repository, event: SessionStarted) -> HookResult:
    if event.source not in ("startup", "clear"):
        return None
    logged = friction.since_last_retro(repository)
    totals = {key: sum(int(str(entry.get(key, 0))) for entry in logged) for key in _THRESHOLDS}
    reached = [f"{totals[key]} {key}" for key, limit in _THRESHOLDS.items() if totals[key] >= limit]
    num_sessions = len({entry.get("session") for entry in logged})
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
    num_summaries, num_new = summaries(transcript)
    if not num_new:
        return None
    return Note(
        for_user=(
            f"Context summary no. {num_summaries} of this session (its transcript has "
            f"{transcript.stat().st_size / 1e6:.0f} MB): Claude goes on from the summary and reads the docs "
            "again. A new session for the next task starts smaller; what is open is in the plan or review file."
        )
    )
