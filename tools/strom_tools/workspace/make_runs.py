"""Running targets of the Makefile, the one definition of the checks and the fixers (`docs/decisions.md`,
Checks): a tool or a hook that needs ruff, mdformat or the docs check runs its target, not the program."""

from strom_tools.workspace.processes import ProcessRun, output, run_process
from strom_tools.workspace.repository import Repository


def run_make(repository: Repository, *arguments: str, silent: bool = True) -> ProcessRun:
    """Runs make with `arguments` (targets and variables, e.g. `fix`, `FILES=a.py`) at the root; `silent`: without
    echoing the recipes. Its stderr ends with make's own line about a failed target."""
    quiet = ["--silent"] if silent else []
    return run_process(["make", "--no-print-directory", *quiet, *arguments], cwd=repository.root)


def problems(run: ProcessRun) -> str:
    """The output of a run that failed (empty if it passed)."""
    return output(run) if run.returncode != 0 else ""
