"""Running targets of the Makefile, the one definition of the checks and the fixers (`docs/decisions.md`,
Checks): a tool or a hook that needs ruff, mdformat or the docs check runs its target, not the program."""

import subprocess
from dataclasses import dataclass

from strom_tools.workspace.repository import Repository


@dataclass(frozen=True)
class MakeRun:
    returncode: int
    stdout: str
    stderr: str
    """With make's own line about a failed target."""


def run_make(repository: Repository, *arguments: str, silent: bool = True) -> MakeRun:
    """Runs make with `arguments` (targets and variables, e.g. `fix`, `FILES=a.py`) at the root; `silent`: without
    echoing the recipes."""
    quiet = ["--silent"] if silent else []
    run = subprocess.run(
        ["make", "--no-print-directory", *quiet, *arguments],
        cwd=repository.root,
        capture_output=True,
        text=True,
        check=False,
    )
    return MakeRun(run.returncode, run.stdout, run.stderr)


def output(run: MakeRun) -> str:
    return f"{run.stdout}{run.stderr}"


def problems(run: MakeRun) -> str:
    """The output of a run that failed (empty if it passed)."""
    return output(run) if run.returncode != 0 else ""
