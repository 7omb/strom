import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from strom_tools.tool_error import ToolError
from strom_tools.workspace import processes
from strom_tools.workspace.processes import ProcessRun, output, pytest_command, run_checked, run_process


def test_a_run_returns_its_exit_code_and_output(tmp_path: Path) -> None:
    script = "import os, sys; print(os.getcwd()); print(os.environ['MARK'], file=sys.stderr); sys.exit(3)"
    run = run_process([sys.executable, "-c", script], cwd=tmp_path, timeout=30, env={"MARK": "marked"})
    assert run == ProcessRun(3, f"{tmp_path.resolve()}\n", "marked\n")


def test_a_timeout_kills_the_whole_group(tmp_path: Path) -> None:
    """The command starts a child that sleeps for a minute and holds the output pipes: the run returns at once
    only if the timeout killed the child too, not just the shell."""
    started_at = time.monotonic()
    run = run_process(["sh", "-c", "echo started; sleep 60 & wait"], cwd=tmp_path, timeout=0.5)
    assert run == ProcessRun(None, "started\n", "")
    assert time.monotonic() - started_at < 30


ECHO = [sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"]


def test_a_run_reads_what_it_is_given_and_otherwise_nothing(tmp_path: Path) -> None:
    """Without `stdin` a command does not read this process's input: a run inside a process that has some (the
    test's own input is empty under pytest, so it would not tell)."""
    assert run_process(ECHO, cwd=tmp_path, stdin="given").stdout == "'given'\n"
    inner = f"from strom_tools.workspace.processes import run_process; print(run_process({ECHO!r}, cwd='.').stdout)"
    env = {**os.environ, "PYTHONPATH": str(Path(processes.__file__).parents[2])}
    outer = subprocess.run(
        [sys.executable, "-c", inner], input="the parent's", env=env, cwd=tmp_path, capture_output=True, text=True
    )
    assert outer.stdout == "''\n\n", outer.stderr


def test_a_checked_run_returns_its_stdout_or_fails_with_its_output(tmp_path: Path) -> None:
    assert run_checked(["sh", "-c", "echo fine"], cwd=tmp_path) == "fine\n"
    with pytest.raises(ToolError, match=r"`sh -c echo broken >&2; exit 2` failed \(exit code 2\):\nbroken"):
        run_checked(["sh", "-c", "echo broken >&2; exit 2"], cwd=tmp_path)
    assert output(ProcessRun(1, "out\n", "err\n")) == "out\nerr\n"


def test_pytest_runs_on_this_interpreter_without_its_cache() -> None:
    assert pytest_command("-q") == [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"]
