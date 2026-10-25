"""Claude Code hooks of this project: the one command `.claude/settings.json` registers, for every event.

Claude can't write `.claude/settings.json` (self-modification), but it can edit this directory: so the
settings register this script once per event, and which handler runs, with which thresholds and options,
is decided here and in the handler modules.

  PostToolUse Edit, MultiEdit, Write   `ruff_hook.after_edit`: format and lint the edited Python file
  PostToolUse Bash                     `rules_hook.after_bash`: load the `.claude/rules` a command touched
  Stop                                 `ruff_hook.at_stop`: lint every changed Python file
  SessionStart                         `friction.at_start`: suggest the skill `retro` after much friction
  SessionEnd                           `friction.at_end`: log the session's friction in `.checks/`

The event arrives as JSON on stdin; a handler returns the exit code (2 blocks and sends stderr to Claude) and
prints its JSON output, if any, on stdout. A handler that crashes is reported and never blocks.
"""

import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import friction  # noqa: E402
import ruff_hook  # noqa: E402
import rules_hook  # noqa: E402

type Handler = Callable[[dict[str, object]], int]

TOOLS: dict[str, Handler] = {
    "Edit": ruff_hook.after_edit,
    "MultiEdit": ruff_hook.after_edit,
    "Write": ruff_hook.after_edit,
    "Bash": rules_hook.after_bash,
}
EVENTS: dict[str, Handler] = {
    "Stop": ruff_hook.at_stop,
    "SessionStart": friction.at_start,
    "SessionEnd": friction.at_end,
}


def main() -> int:
    event: dict[str, object] = json.load(sys.stdin)
    name = event.get("hook_event_name")
    handler = TOOLS.get(str(event.get("tool_name"))) if name == "PostToolUse" else EVENTS.get(str(name))
    if handler is None:
        return 0
    try:
        return handler(event)
    except Exception:  # a broken hook must not block the session
        print(f"hook {handler.__module__}.{handler.__name__} failed:\n{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
