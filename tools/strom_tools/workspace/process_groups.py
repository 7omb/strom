"""`run_detached`: a command in a process group of its own, which a timeout or an interrupt kills as a whole."""

import contextlib
import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from subprocess import PIPE


@dataclass(frozen=True)
class DetachedRun:
    returncode: int | None
    """None after a timeout."""
    stdout: str
    stderr: str


def run_detached(
    command: Sequence[str], *, cwd: Path, timeout: float, env: Mapping[str, str] | None = None
) -> DetachedRun:
    """Runs `command` in its own process group.

    After a timeout, and when this process is interrupted (the group is in its own session, so Ctrl-C does
    not reach it), the whole group is killed, pool workers included. POSIX only (`start_new_session`, `killpg`)."""
    with subprocess.Popen(
        list(command), cwd=cwd, env=env, stdout=PIPE, stderr=PIPE, text=True, start_new_session=True
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_group(process.pid)
            stdout, stderr = process.communicate()
            return DetachedRun(None, stdout, stderr)
        except BaseException:
            _kill_group(process.pid)
            raise
    return DetachedRun(process.returncode, stdout, stderr)


def _kill_group(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError):  # every process of the group has ended already
        os.killpg(pid, signal.SIGKILL)
