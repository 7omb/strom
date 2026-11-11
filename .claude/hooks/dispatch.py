"""Claude Code hooks of this project: the one command `.claude/settings.json` registers, for every event.

Claude can't write `.claude/settings.json` (self-modification), but it can edit this directory: so the
settings register this script once per event, and which handlers run, with which thresholds and options,
is decided here and in the handler modules. What the fixers and the checks are, the Makefile says: the
handlers run its targets (`make fix`, `make lint-python`, `make lint-docs`), as the git hooks do.

  PostToolUse Edit, MultiEdit, Write   `ruff_hook.after_edit`: fix and lint the edited Python file
  PostToolUse Bash                     `rules_hook.after_bash`: load the `.claude/rules` a command touched
  Stop                                 `ruff_hook.at_stop`: fix and lint every changed Python file
                                       `docs_hook.at_stop`: format the changed Markdown files, check the docs
                                       `friction.at_stop`: say when the session's context was summarised
  SessionStart                         `friction.at_start`: suggest the skill `retro` after much friction
  SessionEnd                           `friction.at_end`: log the session's friction in `.checks/`

The event arrives as JSON on stdin; a handler returns the exit code (2 blocks and sends stderr to Claude) and
prints its JSON output, if any, on stdout (one handler per event at most: two outputs are no JSON). Every
handler of an event runs, and the highest exit code counts. A handler that crashes is reported and never
blocks.
"""

import json
import sys
import traceback
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import docs_hook  # noqa: E402
import friction  # noqa: E402
import ruff_hook  # noqa: E402
import rules_hook  # noqa: E402

type Handler = Callable[[dict[str, object]], int]

TOOLS: dict[str, list[Handler]] = {
    "Edit": [ruff_hook.after_edit],
    "MultiEdit": [ruff_hook.after_edit],
    "Write": [ruff_hook.after_edit],
    "Bash": [rules_hook.after_bash],
}
EVENTS: dict[str, list[Handler]] = {
    "Stop": [ruff_hook.at_stop, docs_hook.at_stop, friction.at_stop],
    "SessionStart": [friction.at_start],
    "SessionEnd": [friction.at_end],
}


def main() -> int:
    event: dict[str, object] = json.load(sys.stdin)
    name = str(event.get("hook_event_name"))
    handlers = TOOLS.get(str(event.get("tool_name")), []) if name == "PostToolUse" else EVENTS.get(name, [])
    return max((run(handler, event) for handler in handlers), default=0)


def run(handler: Handler, event: dict[str, object]) -> int:
    try:
        return handler(event)
    except Exception:  # a broken hook must not block the session
        print(f"hook {handler.__module__}.{handler.__name__} failed:\n{traceback.format_exc()}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
