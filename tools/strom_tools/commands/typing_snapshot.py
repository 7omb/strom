"""Saves or compares the diagnostics of mypy, pyright and ty, for a change's typing diffs (skill `validate-change`).

Run:  python bin/typing_snapshot.py save [--name NAME] [--tools TOOL ...]   writes .checks/typing-NAME.txt
      python bin/typing_snapshot.py diff [--name NAME] [--tools TOOL ...]   compares the current ones with it
      python bin/typing_snapshot.py diff --against REV [--tools TOOL ...]   compares them with those of REV

NAME defaults to `before`, the tools to all three. `--against` needs no snapshot: it checks a copy of REV (e.g.
HEAD, main~2, `:index` for the staged changes) in a temporary directory, with this repository's venv and a cold
mypy cache. How the checkers run and what a diagnostic line holds (no line numbers, so that edits elsewhere in a
file show no difference): `strom_tools.change_checks.typing_diagnostics`. A checker that does not run ends the
script instead of counting as one without diagnostics. `diff` lists the removed (`-`) and added (`+`) diagnostics
and exits with 1 if there are any.
"""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.change_checks.typing_diagnostics import Checker, checker_of, diagnostics
from strom_tools.commands import command_line, snapshot_commands
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    names = [checker.value for checker in Checker]
    snapshot_commands.add_arguments(parser)
    parser.add_argument("--tools", nargs="+", choices=names, default=names)
    args = parser.parse_args(argv)
    chosen: list[str] = args.tools
    checkers = [Checker(name) for name in chosen]
    if Checker.MYPY in checkers:
        command_line.require_modules("mypy")

    repository = this_repository()
    asked = snapshot_commands.request(repository, parser, args)

    def diagnostics_in(root: Path) -> list[str]:
        return diagnostics(checkers, root)

    def of_these_tools(line: str) -> bool:  # a diff of fewer tools than saved
        return checker_of(line) in checkers

    return snapshot_commands.save_or_diff(
        repository, asked, kind="typing", what="diagnostics", lines_in=diagnostics_in, kept=of_these_tools
    )
