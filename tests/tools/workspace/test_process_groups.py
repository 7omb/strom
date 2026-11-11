import sys
import time
from pathlib import Path

from strom_tools.workspace.process_groups import DetachedRun, run_detached


def test_a_run_returns_its_exit_code_and_output(tmp_path: Path) -> None:
    script = "import os, sys; print(os.getcwd()); print(os.environ['MARK'], file=sys.stderr); sys.exit(3)"
    run = run_detached([sys.executable, "-c", script], cwd=tmp_path, timeout=30, env={"MARK": "marked"})
    assert run == DetachedRun(3, f"{tmp_path.resolve()}\n", "marked\n")


def test_a_timeout_kills_the_whole_group(tmp_path: Path) -> None:
    """The command starts a child that sleeps for a minute and holds the output pipes: the run returns at once
    only if the timeout killed the child too, not just the shell."""
    started_at = time.monotonic()
    run = run_detached(["sh", "-c", "echo started; sleep 60 & wait"], cwd=tmp_path, timeout=0.5)
    assert run == DetachedRun(None, "started\n", "")
    assert time.monotonic() - started_at < 30
