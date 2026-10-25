"""Saves or compares the diagnostics of mypy, pyright and ty, for a change's typing diffs (skill `validate-change`).

Run:  python bin/typing_snapshot.py save [--name NAME] [--tools TOOL ...]   writes .checks/typing-NAME.txt
      python bin/typing_snapshot.py diff [--name NAME] [--tools TOOL ...]   compares the current ones with it
      python bin/typing_snapshot.py diff --against REV [--tools TOOL ...]   compares them with those of REV

NAME defaults to `before`, the tools to all three (each with the options and paths in `pyproject.toml`;
mypy from this interpreter, pyright and ty from PATH). `--against` needs no snapshot: it checks a copy of
REV (e.g. HEAD, main~2, `:index` for the staged changes) in a temporary directory, with this repository's
venv and a cold mypy cache. A diagnostic is kept as tool, file, severity, rule and message, without line and
column, so that edits elsewhere in a file do not show up as differences; informational ones (pyright's and
ty's `reveal_type` output) are left out. A checker that does not run (missing, a configuration error) ends
the script instead of counting as one without diagnostics. `diff` lists the removed (`-`) and added (`+`)
diagnostics and exits with 1 if there are any.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import NotRequired, TypedDict

from _tools import ROOT, SNAPSHOTS, checkout, diff, require_modules, save_or_diff

_MYPY_LINE = re.compile(r"^(?P<file>[^:\s]+):\d+(?::\d+)?: (?P<severity>error|warning|note): (?P<message>.*)$")
_TY_LINE = re.compile(r"^(?P<file>[^:\s]+):\d+:\d+: (?P<severity>error|warning)\[(?P<rule>[^\]]+)\] (?P<message>.*)$")


class _PyrightDiagnostic(TypedDict):
    """The used part of a diagnostic of `pyright --outputjson`."""

    file: str
    severity: str
    message: str
    rule: NotRequired[str]


def _output(tool: str, command: list[str], summary: str, root: Path) -> str:
    """Stdout of a checker that ran in `root`: exit code 0 or 1 (diagnostics found), and a line matching `summary`."""
    result = subprocess.run(command, cwd=root, capture_output=True, text=True)
    if result.returncode not in (0, 1) or re.search(summary, result.stdout, re.MULTILINE) is None:
        sys.exit(f"{tool} did not run (exit code {result.returncode}):\n{result.stdout}{result.stderr}")
    return result.stdout


def mypy(root: Path) -> list[str]:
    output = _output(
        "mypy", [sys.executable, "-m", "mypy", "--no-pretty"], r"^(Success: no issues|Found \d+ error)", root
    )
    return [
        f"mypy {match['file']}: {match['severity']}: {match['message']}"
        for match in map(_MYPY_LINE.match, output.splitlines())
        if match is not None
    ]


def pyright(root: Path) -> list[str]:
    output = _output("pyright", ["pyright", "--outputjson"], r'"generalDiagnostics"', root)
    diagnostics: list[_PyrightDiagnostic] = json.loads(output)["generalDiagnostics"]
    return [
        f"pyright {Path(each['file']).relative_to(root)}: {each['severity']}[{each.get('rule', '')}]: "
        + " / ".join(line.strip() for line in each["message"].splitlines())
        for each in diagnostics
        if each["severity"] != "information"
    ]


def ty(root: Path) -> list[str]:
    output = _output(
        "ty", ["ty", "check", "--output-format", "concise"], r"^(All checks passed|Found \d+ diagnostic)", root
    )
    return [
        f"ty {match['file']}: {match['severity']}[{match['rule']}]: {match['message']}"
        for match in map(_TY_LINE.match, output.splitlines())
        if match is not None
    ]


TOOLS: dict[str, Callable[[Path], list[str]]] = {"mypy": mypy, "pyright": pyright, "ty": ty}


def diagnostics(tools: list[str], root: Path) -> list[str]:
    return [line for tool in tools for line in TOOLS[tool](root)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Saves or compares the diagnostics of the type checkers.")
    parser.add_argument("action", choices=["save", "diff"])
    parser.add_argument("--name", default="before", help="name of the snapshot (default: before)")
    parser.add_argument("--against", metavar="REV", help="diff: compare with revision REV instead of a snapshot")
    parser.add_argument("--tools", nargs="+", choices=list(TOOLS), default=list(TOOLS))
    args = parser.parse_args()
    if args.against is not None and args.action != "diff":
        parser.error("--against needs `diff`")
    if "mypy" in args.tools:
        require_modules("mypy")
    tools: list[str] = args.tools
    if args.against is not None:
        revision: str = args.against
        with tempfile.TemporaryDirectory(prefix="strom-typing-") as tmp:
            before = diagnostics(tools, checkout(revision, Path(tmp)))
        return diff(before, diagnostics(tools, ROOT), "diagnostics", f"in {revision}")
    return save_or_diff(
        args.action,
        SNAPSHOTS / f"typing-{args.name}.txt",
        diagnostics(tools, ROOT),
        "diagnostics",
        lambda line: line.split(" ", 1)[0] in tools,  # a diff of fewer tools than saved
    )


if __name__ == "__main__":
    sys.exit(main())
