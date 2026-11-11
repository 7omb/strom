"""Logs each session's friction, suggests a retrospective when it piles up and says when a session outgrows its
context (called by `dispatch.py`).

SessionEnd    appends the session's friction to `.checks/friction.jsonl` (`bin/sessions.py`, friction)
              and removes what `rules_hook` kept for the session.
SessionStart  sums the lines logged since the last retrospective; past a threshold (`THRESHOLDS`, after
              at least `MIN_SESSIONS`) it tells the user and Claude to run the skill `retro`.
Stop          tells the user, once per summary of the session's context, that a new session starts smaller.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
sys.path.insert(0, str(ROOT / "bin"))

import sessions  # noqa: E402

MIN_SESSIONS = 3
THRESHOLDS = {"hook_blocks": 40, "tool_errors": 25, "rejected": 4, "interrupts": 6}
"""Sums since the last retrospective; reaching any one suggests the next."""


def at_end(event: dict[str, object]) -> int:
    transcript = event.get("transcript_path")
    if isinstance(transcript, str) and Path(transcript).exists():
        sessions.log_friction(Path(transcript))
    (ROOT / ".checks" / "rules-loaded" / f"{event.get('session_id')}.txt").unlink(missing_ok=True)
    return 0


def at_start(event: dict[str, object]) -> int:
    if event.get("source") not in ("startup", "clear"):
        return 0
    logged = sessions.since_last_retro()
    totals = {key: sum(int(str(entry.get(key, 0))) for entry in logged) for key in THRESHOLDS}
    reached = [f"{totals[key]} {key}" for key, limit in THRESHOLDS.items() if totals[key] >= limit]
    num_sessions = len({entry.get("session") for entry in logged})
    if num_sessions < MIN_SESSIONS or not reached:
        return 0
    note = (
        f"Friction in the {num_sessions} sessions since the last retrospective: {', '.join(reached)}. "
        "Consider running the skill `retro` (it proposes fixes to CLAUDE.md, .claude/ and bin/)."
    )
    output = {"systemMessage": note, "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note}}
    print(json.dumps(output))
    return 0


def at_stop(event: dict[str, object]) -> int:
    transcript = event.get("transcript_path")
    if not isinstance(transcript, str) or not Path(transcript).exists():
        return 0
    num_summaries, num_new = sessions.summaries(Path(transcript))
    if num_new:
        note = (
            f"Context summary no. {num_summaries} of this session (its transcript has "
            f"{Path(transcript).stat().st_size / 1e6:.0f} MB): Claude goes on from the summary and reads the docs "
            "again. A new session for the next task starts smaller; what is open is in the plan or review file."
        )
        print(json.dumps({"systemMessage": note}))
    return 0
