"""Formats and lints the Python files Claude changed (called by `dispatch.py`).

Runs `ruff format` and `ruff check --fix` (options from `pyproject.toml`, ruff from the dev shell) on
  - PostToolUse (Edit, Write): the edited file, if it is in this repository (a probe script in the
    scratchpad is left as written). The rules a half-done change breaks (`IN_BETWEEN`: an import
    added before its use or removed before its last use, a name used before it is defined or moved) are
    neither fixed nor reported here: a fix would delete the new import, and a report blocks every step of a
    refactoring (186 blocks in four sessions, 2026-11-04 to 06).
  - Stop (the end of a turn): every changed Python file (uncommitted changes, untracked files not ignored),
    with all rules; this also covers files changed by commands rather than by Edit or Write. It blocks once
    per turn (a second stop with `stop_hook_active` passes, so that a file Claude can't fix ends no loop).
Lint errors that remain are reported back to Claude (exit code 2, on stderr).
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
PYTHON = (".py", ".pyi")
IN_BETWEEN = ["F401", "F811", "F821", "F822", "F841"]


def changed_files() -> list[str]:
    """The Python files with uncommitted changes or untracked (and not ignored), relative to the root."""
    listed = subprocess.run(  # noqa: S603
        ["git", "ls-files", "-z", "--modified", "--others", "--exclude-standard"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    staged = subprocess.run(  # noqa: S603
        ["git", "diff", "-z", "--name-only", "--cached"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    names = {name for name in (listed + staged).split("\0") if name}
    return sorted(name for name in names if Path(name).suffix in PYTHON and (ROOT / name).exists())


def ruff(files: list[str], ignore: list[str]) -> str:
    """Formats and fixes `files`; the lint errors that remain (empty if none)."""
    subprocess.run(["ruff", "format", "--quiet", *files], cwd=ROOT, check=False)  # noqa: S603, S607
    check = subprocess.run(  # noqa: S603
        ["ruff", "check", "--fix", "--quiet", *(["--ignore", ",".join(ignore)] if ignore else []), *files],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return f"{check.stdout}{check.stderr}" if check.returncode != 0 else ""


def after_edit(event: dict[str, object]) -> int:
    tool_input = event.get("tool_input")
    file_path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if not isinstance(file_path, str) or Path(file_path).suffix not in PYTHON or not Path(file_path).exists():
        return 0
    if not Path(file_path).resolve().is_relative_to(ROOT):
        return 0  # not this project's code (a probe in the scratchpad): its rules do not apply
    return report(ruff([file_path], IN_BETWEEN), "after the edit")


def at_stop(event: dict[str, object]) -> int:
    if event.get("stop_hook_active") is True:
        return 0
    files = changed_files()
    return report(ruff(files, []) if files else "", "in the changed files")


def report(errors: str, where: str) -> int:
    if errors:
        print(f"ruff check {where}:\n{errors}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # registered directly by an older `.claude/settings.json`
    import json

    event: dict[str, object] = json.load(sys.stdin)
    sys.exit(at_stop(event) if event.get("hook_event_name") == "Stop" else after_edit(event))
