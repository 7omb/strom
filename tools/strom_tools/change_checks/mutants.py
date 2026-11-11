"""The tests against a copy of the code with an injected bug: whether they catch it.

The library (`src/` of the working tree), the tools (`_MUTABLE`), the tests and `pyproject.toml` are copied into a
directory, and pytest runs there, with the copy of the library first on PYTHONPATH (`library_copy` checks that
`import strom` finds it) and in its own process group (injected bugs often hang, a join waiting forever, so a
timeout kills the whole group, pool workers included). The same tests run on the copy without the bug first: they
must pass there, so that a failure means the bug was caught (not a test that fails anyway, nor a missing pytest).
Nothing in the repository changes, also not its caches or Hypothesis database."""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from strom_tools.change_checks.revisions import Revision, WorkingTree, export, library_copy, python_path_env
from strom_tools.tool_error import ToolError
from strom_tools.workspace import git_files
from strom_tools.workspace.processes import ProcessRun, pytest_command, run_process
from strom_tools.workspace.repository import Repository

_MUTABLE = ["tools", "bin", ".claude/hooks"]
"""What the copy holds of the working tree besides the library: the tools, with the wrappers their tests read."""
_DEFAULT_PYTEST_ARGS = ["-x", "-q"]


@dataclass(frozen=True)
class Replace:
    file: str
    """Its path from the root."""
    old: str
    """Must occur exactly once in the file."""
    new: str


@dataclass(frozen=True)
class Patch:
    path: Path
    """A patch file (`git diff` format, paths relative to the root)."""


type Bug = Replace | Patch


def _inject(copy: Path, bug: Bug) -> None:
    """Injects the bug into the copy of the repository at `copy`."""
    match bug:
        case Patch(path):
            git_files.apply_patch(copy, path.resolve())
        case Replace(file, old, new):
            target = copy / file
            text = target.read_text()
            if text.count(old) != 1:
                raise ToolError(f"OLD occurs {text.count(old)} times in {file}, not once")
            target.write_text(text.replace(old, new))


@dataclass(frozen=True)
class Trial:
    clean: ProcessRun
    """The tests on the copy without the bug."""
    mutant: ProcessRun | None
    """The tests on the copy with the bug; None if they did not pass without it."""


class Verdict(Enum):
    CAUGHT = "caught"
    """A test failed."""
    MISSED = "missed"
    """Every test passed."""
    HUNG = "hung"
    """Killed after the timeout."""
    UNDECIDED = "no verdict"
    """The tests do not pass without the bug, or pytest ended otherwise (e.g. a collection error)."""


def verdict(trial: Trial) -> Verdict:
    if trial.mutant is None:
        return Verdict.UNDECIDED
    match trial.mutant.returncode:
        case 1:
            return Verdict.CAUGHT
        case 0:
            return Verdict.MISSED
        case None:
            return Verdict.HUNG
        case _:
            return Verdict.UNDECIDED


def ended(run: ProcessRun) -> str:
    """How a run of the tests ended: `hung`, or `exit code N`."""
    return "hung" if run.returncode is None else f"exit code {run.returncode}"


def failed_tests(run: ProcessRun) -> list[str]:
    """pytest's lines about the tests that failed or erred in a run."""
    return [line for line in run.stdout.splitlines() if line.startswith(("FAILED", "ERROR"))]


def _exits_first_in_workers(pytest_args: Sequence[str]) -> bool:
    """Whether the arguments ask for both `-x` and pytest-xdist's workers (`-n`)."""
    exits_first = any(arg in ("-x", "--exitfirst") for arg in pytest_args)
    return exits_first and any(arg.startswith(("-n", "--numprocesses")) for arg in pytest_args)


def try_bug(
    repository: Repository, bug: Bug, tests_from: Revision, pytest_args: Sequence[str], timeout: float, copy: Path
) -> Trial:
    """Runs the tests of `tests_from` in the empty directory `copy`, without the bug and, if they pass, with it;
    each run ends after `timeout` seconds at the latest."""
    if _exits_first_in_workers(pytest_args):
        raise ToolError(
            "`-x` with `-n`: pytest-xdist ends with exit code 2 at the first failure, which reads as no verdict"
            " (drop one of them)"
        )
    command = pytest_command(*(pytest_args or _DEFAULT_PYTEST_ARGS))
    src = library_copy(repository, WorkingTree(), copy)
    export(repository, WorkingTree(), _MUTABLE, copy)
    export(repository, tests_from, ["tests", "pyproject.toml"], copy)
    # no bytecode of the clean run: a bug of the same length, injected within the second of the file's
    # modification time, would run from the cache of the code without it
    env = {**python_path_env(src), "PYTHONDONTWRITEBYTECODE": "1"}
    clean = run_process(command, cwd=copy, timeout=timeout, env=env)
    if clean.returncode != 0:
        return Trial(clean, None)
    _inject(copy, bug)
    return Trial(clean, run_process(command, cwd=copy, timeout=timeout, env=env))
