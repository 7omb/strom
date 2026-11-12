"""The make targets of `make check`, each as one line; the commands stay in the Makefile, so this and
`make check` don't drift apart."""

import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from strom_tools.workspace.make_runs import run_make
from strom_tools.workspace.processes import output
from strom_tools.workspace.repository import Repository

TARGETS = ["lint", "type", "cov", "examples"]
"""The targets of `make check` (a test compares them with the Makefile)."""


@dataclass(frozen=True)
class TargetRun:
    target: str
    passed: bool
    run_time: float
    """Seconds it took."""
    output: str


def run_targets(repository: Repository, targets: Sequence[str]) -> Iterator[TargetRun]:
    """Runs every target, also after a failure, and yields each as it ends."""
    for target in targets:
        started_at = time.monotonic()
        run = run_make(repository, target, silent=False)
        yield TargetRun(target, run.returncode == 0, time.monotonic() - started_at, output(run))


def summary(run: TargetRun) -> str:
    """The target, `ok` or `FAILED`, its time and the last line of its output (e.g. pytest's counts)."""
    lines = [line for line in run.output.splitlines() if line.strip() and not line.startswith("make: ")]
    status = "ok" if run.passed else "FAILED"
    return f"{run.target:9} {status:6} {run.run_time:6.1f}s  {lines[-1][:100] if lines else ''}"
