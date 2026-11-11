"""The one command `.claude/settings.json` registers, for every event: which handlers an event has.

Claude can't write `.claude/settings.json` (self-modification): so the settings register the wrapper
`.claude/hooks/dispatch.py` once per event, and which handlers run, with which thresholds and options, is
decided here and in the handler modules. What the fixers and the checks are, the Makefile says: the handlers
run its targets (`make fix`, `make lint-python`, `make lint-docs`), as the git hooks do.

  PostToolUse Edit, MultiEdit, Write   `python_fixes.after_edit`: fix and lint the edited Python file
  PostToolUse Bash                     `rules_loading.after_bash`: load the `.claude/rules` a command touched
  Stop                                 `python_fixes.at_stop`: fix and lint every changed Python file
                                       `docs_fixes.at_stop`: format the changed Markdown files, check the docs
                                       `friction_notes.at_stop`: say when the session's context was summarised
  SessionStart                         `friction_notes.at_start`: suggest the skill `retro` after much friction
  SessionEnd                           `friction_notes.at_end`: log the session's friction
                                       `rules_loading.at_end`: forget what it loaded in the session

A handler takes the repository and its event and returns a `HookResult` (`hook_results`). Every handler of an
event runs; one that raises is reported and never blocks."""

import sys
from collections.abc import Callable, Mapping, Sequence

from strom_tools.hooks import docs_fixes, friction_notes, python_fixes, rules_loading
from strom_tools.hooks.hook_events import HookEvent, SessionEnded, SessionStarted, ToolUsed, TurnEnded, parse
from strom_tools.hooks.hook_results import Failed, HookResult, answer
from strom_tools.json_objects import parsed
from strom_tools.workspace.repository import Repository, this_repository

type _Handler[E] = Callable[[Repository, E], HookResult]

_AFTER_TOOL: Mapping[str, Sequence[_Handler[ToolUsed]]] = {
    "Edit": [python_fixes.after_edit],
    "MultiEdit": [python_fixes.after_edit],
    "Write": [python_fixes.after_edit],
    "Bash": [rules_loading.after_bash],
}
_AT_STOP: Sequence[_Handler[TurnEnded]] = [python_fixes.at_stop, docs_fixes.at_stop, friction_notes.at_stop]
_AT_START: Sequence[_Handler[SessionStarted]] = [friction_notes.at_start]
_AT_END: Sequence[_Handler[SessionEnded]] = [friction_notes.at_end, rules_loading.at_end]


def _results(repository: Repository, event: HookEvent) -> list[HookResult | Failed]:
    """What each handler of the event returns, in the order of its table."""
    match event:
        case ToolUsed():
            return [_run(handler, repository, event) for handler in _AFTER_TOOL.get(event.tool, ())]
        case TurnEnded():
            return [_run(handler, repository, event) for handler in _AT_STOP]
        case SessionStarted():
            return [_run(handler, repository, event) for handler in _AT_START]
        case SessionEnded():
            return [_run(handler, repository, event) for handler in _AT_END]


def _run[E](handler: _Handler[E], repository: Repository, event: E) -> HookResult | Failed:
    try:
        return handler(repository, event)
    except Exception:  # a broken hook must not block the session
        import traceback  # here: its import takes longer than everything else the hook command does

        module: str = handler.__module__
        name: str = getattr(handler, "__name__", repr(handler))
        return Failed(f"hook {module}.{name} failed:\n{traceback.format_exc()}")


def main() -> int:
    payload: str = sys.stdin.read()
    event = parse(parsed(payload))
    if event is None:
        return 0
    answered = answer(event, _results(this_repository(), event))
    sys.stdout.write(answered.stdout)
    sys.stderr.write(answered.stderr)
    return answered.exit_code
