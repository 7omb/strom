"""The test IDs pytest collects, for restructuring tests: every difference has to be explained."""

import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from strom_tools.tool_error import ToolError


def collected(pytest_args: Sequence[str], root: Path, env: Mapping[str, str] | None = None) -> list[str]:
    """The IDs of the tests that `pytest --collect-only` finds in `root` (`pytest_args` select them; default:
    `testpaths`)."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *pytest_args],
        cwd=root,
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise ToolError(f"collection failed (exit code {result.returncode}):\n{result.stdout}")
    return [line for line in result.stdout.splitlines() if "::" in line]
