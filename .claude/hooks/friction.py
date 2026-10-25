"""Logs each session's friction and suggests a retrospective when it piles up (called by `dispatch.py`).

SessionEnd    appends the session's counts to `.checks/friction.jsonl` (`bin/sessions.py`, friction)
              and removes what `rules_hook` kept for the session.
SessionStart  sums the sessions logged since the last retrospective; past a threshold (`THRESHOLDS`, after
              at least `MIN_SESSIONS`) it tells the user and Claude to run the skill `retro`.
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
        sessions.log_friction(sessions.friction(Path(transcript)))
    (ROOT / ".checks" / "rules-loaded" / f"{event.get('session_id')}.txt").unlink(missing_ok=True)
    return 0


def at_start(event: dict[str, object]) -> int:
    if event.get("source") not in ("startup", "clear"):
        return 0
    logged = sessions.since_last_retro()
    totals = {key: sum(int(str(entry.get(key, 0))) for entry in logged) for key in THRESHOLDS}
    reached = [f"{totals[key]} {key}" for key, limit in THRESHOLDS.items() if totals[key] >= limit]
    if len(logged) < MIN_SESSIONS or not reached:
        return 0
    note = (
        f"Friction in the {len(logged)} sessions since the last retrospective: {', '.join(reached)}. "
        "Consider running the skill `retro` (it proposes fixes to CLAUDE.md, .claude/ and bin/)."
    )
    output = {"systemMessage": note, "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note}}
    print(json.dumps(output))
    return 0
