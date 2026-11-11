"""Saves or compares the test IDs pytest collects, for restructuring tests (skill `validate-change`).

Run:  python bin/collect_ids.py save [--name NAME] [-- PYTEST_ARGS]   writes .checks/collect-ids-NAME.txt
      python bin/collect_ids.py diff [--name NAME] [-- PYTEST_ARGS]   compares the current IDs with it
      python bin/collect_ids.py diff --against REV [-- PYTEST_ARGS]   compares them with those of REV

NAME defaults to `before`; PYTEST_ARGS select what is collected (default: `testpaths`). `--against` needs
no snapshot: it collects in a copy of REV (e.g. HEAD, main~2, `:index` for the staged changes) in a temporary
directory, with REV's library first on PYTHONPATH. `diff` lists the removed (`-`) and added (`+`) IDs and
exits with 1 if there are any: explain every difference.
"""

from collections.abc import Sequence
from pathlib import Path

from strom_tools.change_checks.collected_ids import collected
from strom_tools.change_checks.revisions import python_path_env
from strom_tools.commands import command_line, snapshot_commands
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    own, pytest_args = command_line.split_passthrough(argv)
    parser = command_line.parser(__doc__)
    snapshot_commands.add_arguments(parser)
    args = parser.parse_args(own)
    repository = this_repository()
    asked = snapshot_commands.request(repository, parser, args)
    command_line.require_modules("pytest")

    def ids_in(root: Path) -> list[str]:
        # the library of `root` first: a copy's, or in the repository the one its editable install points to
        return collected(pytest_args, root, python_path_env(root / "src"))

    return snapshot_commands.save_or_diff(repository, asked, kind="collect-ids", what="IDs", lines_in=ids_in)
