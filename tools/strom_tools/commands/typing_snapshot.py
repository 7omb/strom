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

from collections.abc import Sequence
from pathlib import Path

from strom_tools.change_checks.typing_diagnostics import TOOLS, diagnostics
from strom_tools.commands import command_line, snapshots
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    checkers = list(TOOLS)
    snapshots.add_arguments(parser)
    parser.add_argument("--tools", nargs="+", choices=checkers, default=checkers)
    args = parser.parse_args(argv)
    tools: list[str] = args.tools
    if "mypy" in tools:
        command_line.require_modules("mypy")

    def diagnostics_in(root: Path, is_copy: bool) -> list[str]:
        return diagnostics(tools, root)

    def of_these_tools(line: str) -> bool:  # a diff of fewer tools than saved
        return line.split(" ", 1)[0] in tools

    return snapshots.save_or_diff(
        this_repository(),
        parser,
        args,
        kind="typing",
        what="diagnostics",
        lines_in=diagnostics_in,
        kept=of_these_tools,
    )
