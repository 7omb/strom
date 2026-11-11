"""The examples in `examples/`: each a uv script that runs in an environment of its own and checks its results.

What an example has to be, and how it is run and type-checked: `strom_tools.commands.run_examples`."""

import json
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace.processes import output, run_checked, run_process
from strom_tools.workspace.repository import Repository

_TIMEOUT = 120.0  # seconds per example (the first run of a script also installs its environment)
_TIMEOUTS: dict[str, float] = {}  # per example (file name), where the default does not fit
_SCRIPT_BLOCK = re.compile(r"(?m)^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$")  # PEP 723's own regex
_LOCK_COMMAND = "python bin/run_examples.py --lock"


@dataclass(frozen=True)
class Passed:
    """It ran, or type-checked, as expected."""

    stdout: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class StaleLock:
    """Its lock file does not fit its header (or strom's dependency groups): it did not run."""

    lock: str
    """The lock file's name."""


@dataclass(frozen=True)
class Failed:
    exit_code: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TimedOut:
    timeout: float
    """Seconds."""
    stdout: str
    stderr: str


@dataclass(frozen=True)
class TypeErrors:
    checkers: tuple[str, ...]
    """The checkers that reported some."""
    output: str
    """Theirs, each under a line `--- CHECKER`."""


type Outcome = Passed | StaleLock | Failed | TimedOut | TypeErrors


def described(outcome: Outcome) -> str:
    """The outcome in a few words: `ok`, a stale lock and how to update it, `exit code N`, `timeout after N s`,
    `type errors (CHECKER, ...)`."""
    match outcome:
        case Passed():
            return "ok"
        case StaleLock(lock):
            return f"stale lock {lock} (update: {_LOCK_COMMAND})"
        case Failed(exit_code):
            return f"exit code {exit_code}"
        case TimedOut(timeout):
            return f"timeout after {timeout:g} s"
        case TypeErrors(checkers):
            return f"type errors ({', '.join(checkers)})"


def shown_output(outcome: Outcome) -> str:
    """What the example or the checkers wrote, under the lines `--- stdout` and `--- stderr`."""
    match outcome:
        case Passed(stdout, stderr) | Failed(_, stdout, stderr) | TimedOut(_, stdout, stderr):
            return f"--- stdout\n{stdout}--- stderr\n{stderr}"
        case StaleLock():
            return "--- stdout\n--- stderr\n"
        case TypeErrors(_, output):
            return f"--- stdout\n{output}--- stderr\n"


def examples(repository: Repository, names: list[str]) -> list[Path]:
    """The examples to run: all (every `examples/*.py` whose name does not start with `_`), or the named ones
    (`simple` or `simple.py`; an unknown name is a `ToolError`)."""
    directory = repository.root / "examples"
    every = {path.name: path for path in sorted(directory.glob("*.py")) if not path.name.startswith("_")}
    if not names:
        return list(every.values())
    wanted = [name if name.endswith(".py") else f"{name}.py" for name in names]
    unknown = [name for name in wanted if name not in every]
    if unknown:
        raise ToolError(f"unknown examples: {', '.join(unknown)} (known: {', '.join(every)})")
    return [every[name] for name in wanted]


def _require_header(example: Path) -> None:
    """A `ToolError` unless the example has a script header: every example is a uv script."""
    if _SCRIPT_BLOCK.search(example.read_text(encoding="utf-8")) is None:
        raise ToolError(f"{example.name}: no `# /// script` header (see `bin/run_examples.py --help`)")


def run(example: Path) -> Passed | StaleLock | Failed | TimedOut:
    """Runs one example (unless its lock is stale)."""
    if (stale := _stale_lock(example)) is not None:
        return stale
    command = ["uv", "run", "--script", "--locked", "--quiet", "--python", sys.executable, str(example)]
    timeout = _TIMEOUTS.get(example.name, _TIMEOUT)
    with tempfile.TemporaryDirectory() as cwd:
        ran = run_process(command, cwd=Path(cwd), timeout=timeout)
    match ran.returncode:
        case None:
            return TimedOut(timeout, ran.stdout, ran.stderr)
        case 0:
            return Passed(ran.stdout, ran.stderr)
        case exit_code:
            return Failed(exit_code, ran.stdout, ran.stderr)


def _stale_lock(example: Path) -> StaleLock | None:
    """None if the example's lock file fits its header (and strom's `pyproject.toml`, whose dependency groups it
    records). A `ToolError` for an example without a header."""
    _require_header(example)
    check = run_process(["uv", "lock", "--script", str(example), "--check", "--quiet"], cwd=example.parent)
    return None if check.returncode == 0 else StaleLock(f"{example.name}.lock")


def lock(example: Path) -> None:
    """Updates the lock file of an example (`uv lock --script`)."""
    _require_header(example)
    run_checked(["uv", "lock", "--script", str(example)], cwd=example.parent)


def check_types(repository: Repository, example: Path) -> Passed | StaleLock | TypeErrors:
    """mypy, pyright and ty on one example, with the options of the repository's `pyproject.toml` against its
    script's environment."""
    if (stale := _stale_lock(example)) is not None:
        return stale
    sync = ["uv", "sync", "--script", str(example), "--locked", "--quiet", "--python", sys.executable]
    run_checked(sync, cwd=example.parent)
    python_of = ["uv", "python", "find", "--script", str(example)]  # the environment `uv sync` just made
    python = run_checked(python_of, cwd=example.parent).strip()
    environment = Path(python).parent.parent
    failed: list[str] = []
    reported = ""
    with tempfile.TemporaryDirectory() as config_dir:
        # pyright's `venv` in pyproject.toml outranks `--pythonpath`: a config of its own names the environment
        pyright_config = Path(config_dir) / "pyrightconfig.json"
        config: dict[str, str] = {
            "pythonVersion": "3.14",
            "venvPath": str(environment.parent),
            "venv": environment.name,
        }
        pyright_config.write_text(json.dumps(config))
        tools = {
            "mypy": [sys.executable, "-m", "mypy", "--no-pretty", "--python-executable", python, str(example)],
            "pyright": ["pyright", "--project", str(pyright_config), str(example)],
            "ty": ["ty", "check", "--python", python, str(example)],
        }
        for tool, command in tools.items():
            result = run_process(command, cwd=repository.root)
            if result.returncode != 0:
                failed.append(tool)
                reported += f"--- {tool}\n{output(result)}"
    return TypeErrors(tuple(failed), reported) if failed else Passed()
