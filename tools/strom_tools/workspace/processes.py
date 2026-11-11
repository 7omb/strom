"""`run_process`: every command the tools start, in a process group of its own, which a timeout or an interrupt
kills as a whole; its outcome is a `ProcessRun`. Only this module starts processes (`tests/tools/test_structure.py`
checks it)."""

import contextlib
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import DEVNULL, PIPE

from strom_tools.tool_error import ToolError


@dataclass(frozen=True)
class ProcessRun:
    returncode: int | None
    """None after a timeout."""
    stdout: str
    stderr: str


def run_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stdin: str | None = None,
) -> ProcessRun:
    """Runs `command` in its own process group, with `stdin` as its input (default: none), and collects its output.

    After `timeout` seconds, and when this process is interrupted (the group is in its own session, so Ctrl-C does
    not reach it), the whole group is killed, pool workers included. POSIX only (`start_new_session`, `killpg`)."""
    with subprocess.Popen(
        list(command),
        cwd=cwd,
        env=env,
        stdin=DEVNULL if stdin is None else PIPE,
        stdout=PIPE,
        stderr=PIPE,
        text=True,
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(stdin, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process.pid)
            stdout, stderr = process.communicate()
            return ProcessRun(None, stdout, stderr)
        except BaseException:
            _kill_group(process.pid)
            raise
    return ProcessRun(process.returncode, stdout, stderr)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):  # every process of the group has ended already
        os.killpg(pid, signal.SIGKILL)


def output(run: ProcessRun) -> str:
    return f"{run.stdout}{run.stderr}"


def run_checked(
    command: Sequence[str], *, cwd: Path, env: Mapping[str, str] | None = None, stdin: str | None = None
) -> str:
    """The stdout of `command`; a `ToolError` with its output if it fails."""
    run = run_process(command, cwd=cwd, env=env, stdin=stdin)
    if run.returncode != 0:
        raise ToolError(f"`{' '.join(command)}` failed (exit code {run.returncode}):\n{output(run)}")
    return run.stdout


def pytest_command(*arguments: str) -> list[str]:
    """pytest on this interpreter, without its cache (a run in a copy leaves nothing in the repository's)."""
    return [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *arguments]
