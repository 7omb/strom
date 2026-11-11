"""The diagnostics of mypy, pyright and ty as comparable lines.

A diagnostic is kept as tool, file, severity, rule and message, without line and column, so that edits
elsewhere in a file do not show up as differences; informational ones (pyright's and ty's `reveal_type` output)
are left out. A checker that does not run (missing, a configuration error) is a `ToolError`, not a checker
without diagnostics. Each checker runs with the options and paths of the `pyproject.toml` in its directory:
mypy from this interpreter, pyright and ty from PATH."""

import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import NotRequired, TypedDict

from strom_tools.tool_error import ToolError
from strom_tools.workspace.processes import output, run_process

_MYPY_LINE = re.compile(r"^(?P<file>[^:\s]+):\d+(?::\d+)?: (?P<severity>error|warning|note): (?P<message>.*)$")
_TY_LINE = re.compile(r"^(?P<file>[^:\s]+):\d+:\d+: (?P<severity>error|warning)\[(?P<rule>[^\]]+)\] (?P<message>.*)$")


class _PyrightDiagnostic(TypedDict):
    """The used part of a diagnostic of `pyright --outputjson`."""

    file: str
    severity: str
    message: str
    rule: NotRequired[str]


class _PyrightReport(TypedDict):
    generalDiagnostics: list[_PyrightDiagnostic]


def _output(tool: str, command: Sequence[str], summary: str, root: Path) -> str:
    """Stdout of a checker that ran in `root`: exit code 0 or 1 (diagnostics found), and a line matching `summary`."""
    result = run_process(command, cwd=root)
    if result.returncode not in (0, 1) or re.search(summary, result.stdout, re.MULTILINE) is None:
        raise ToolError(f"{tool} did not run (exit code {result.returncode}):\n{output(result)}")
    return result.stdout


def _mypy(root: Path) -> list[str]:
    command = [sys.executable, "-m", "mypy", "--no-pretty"]
    return _mypy_lines(_output("mypy", command, r"^(Success: no issues|Found \d+ error)", root))


def _mypy_lines(output: str) -> list[str]:
    """The diagnostics in the output of `mypy --no-pretty`."""
    matches = map(_MYPY_LINE.match, output.splitlines())
    return [match.expand(r"mypy \g<file>: \g<severity>: \g<message>") for match in matches if match is not None]


def _pyright(root: Path) -> list[str]:
    return _pyright_lines(_output("pyright", ["pyright", "--outputjson"], r'"generalDiagnostics"', root), root)


def _pyright_lines(output: str, root: Path) -> list[str]:
    """The diagnostics in the output of `pyright --outputjson`, their files from `root`."""
    report: _PyrightReport = json.loads(output)
    return [
        f"pyright {Path(each['file']).relative_to(root)}: {each['severity']}[{each.get('rule', '')}]: "
        + " / ".join(line.strip() for line in each["message"].splitlines())
        for each in report["generalDiagnostics"]
        if each["severity"] != "information"
    ]


def _ty(root: Path) -> list[str]:
    command = ["ty", "check", "--output-format", "concise"]
    return _ty_lines(_output("ty", command, r"^(All checks passed|Found \d+ diagnostic)", root))


def _ty_lines(output: str) -> list[str]:
    """The diagnostics in the output of `ty check --output-format concise`."""
    matches = map(_TY_LINE.match, output.splitlines())
    return [match.expand(r"ty \g<file>: \g<severity>[\g<rule>]: \g<message>") for match in matches if match is not None]


class Checker(Enum):
    """A type checker, by the name its diagnostics start with."""

    MYPY = "mypy"
    PYRIGHT = "pyright"
    TY = "ty"


_RUNS: Mapping[Checker, Callable[[Path], list[str]]] = {
    Checker.MYPY: _mypy,
    Checker.PYRIGHT: _pyright,
    Checker.TY: _ty,
}


def diagnostics(checkers: Sequence[Checker], root: Path) -> list[str]:
    """The diagnostics of `checkers` for the project in `root`."""
    return [line for checker in checkers for line in _RUNS[checker](root)]


def checker_of(line: str) -> Checker | None:
    """The checker a line of `diagnostics` comes from; None for a line that is none."""
    name = line.split(" ", 1)[0]
    return next((checker for checker in Checker if checker.value == name), None)
