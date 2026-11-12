"""The test IDs pytest collects, for restructuring tests: every difference has to be explained."""

from collections.abc import Mapping, Sequence
from pathlib import Path

from strom_tools.tool_error import ToolError
from strom_tools.workspace.processes import output, pytest_command, run_process


def collected(pytest_args: Sequence[str], root: Path, env: Mapping[str, str] | None = None) -> list[str]:
    """The IDs of the tests that `pytest --collect-only` finds in `root` (`pytest_args` select them; default:
    `testpaths`), in the order they are defined (not pytest-randomly's)."""
    command = pytest_command("--collect-only", "-q", "-p", "no:randomly", *pytest_args)
    result = run_process(command, cwd=root, env=env)
    if result.returncode != 0:
        raise ToolError(f"collection failed (exit code {result.returncode}):\n{output(result)}")
    return [line for line in result.stdout.splitlines() if "::" in line]
