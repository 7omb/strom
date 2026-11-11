"""Fixes and lints the Python files Claude changed.

Runs `make fix lint-python` on them (the Makefile: what ruff can fix, its formatter, then its report):
  - after an Edit or a Write, on the edited file, if it is in this repository (a probe script in the scratchpad
    is left as written). The rules a half-done change breaks (`_IN_BETWEEN`: an import added before its use or
    removed before its last use, a name used before it is defined or moved) are neither fixed nor reported
    here: a fix would delete the new import, and a report blocks every step of a refactoring (186 blocks in four
    sessions, 2026-11-04 to 06);
  - at the end of a turn, on every changed Python file (uncommitted changes, untracked files not ignored), with
    all rules; this also covers files changed by commands rather than by Edit or Write. It blocks once per turn
    (a second stop passes, so that a file Claude can't fix ends no loop).
What ruff reports goes back to Claude."""

from pathlib import Path

from strom_tools.hooks.hook_events import Block, HookResult, ToolUsed, TurnEnded
from strom_tools.workspace import git_files
from strom_tools.workspace.make_targets import MakeRun, problems, run_make
from strom_tools.workspace.repository import Repository

_PYTHON = (".py", ".pyi")
_IN_BETWEEN = ["F401", "F811", "F821", "F822", "F841"]


def after_edit(repository: Repository, event: ToolUsed) -> HookResult:
    if event.file_path is None:
        return None
    edited = Path(event.file_path)
    if edited.suffix not in _PYTHON or not edited.exists():
        return None
    if not edited.resolve().is_relative_to(repository.root):
        return None  # not this project's code (a probe in the scratchpad): its rules do not apply
    unfinished = f"ARGS=--ignore {','.join(_IN_BETWEEN)}"
    return _reported(run_make(repository, "fix", "lint-python", f"FILES={edited}", unfinished), "after the edit")


def at_stop(repository: Repository, event: TurnEnded) -> HookResult:
    if event.again:
        return None
    files = [name for name in git_files.changed(repository) if Path(name).suffix in _PYTHON]
    if not files:
        return None
    return _reported(run_make(repository, "fix", "lint-python", f"FILES={' '.join(files)}"), "in the changed files")


def _reported(run: MakeRun, where: str) -> HookResult:
    errors = problems(run)
    return Block(f"ruff check {where}:\n{errors}") if errors else None
