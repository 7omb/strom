"""Prints the hash of a new commit of the working tree, to compare later edits with (skill `validate-change`).

Run:  python bin/baseline.py

The commit holds the files git sees (tracked ones and untracked ones that are not ignored) as they are now, with
HEAD as its parent; it is made in an index file of its own, so the index (the user's), the branches and the
working tree stay as they are. Pass the hash as REV to `bin/typing_snapshot.py diff --against`,
`bin/collect_ids.py diff --against`, `bin/mutant.py --tests-from` or `bin/ab.py`. The commit hangs on no ref, so
`git gc` prunes it after some weeks: a measurement that the docs cite names a tag of it
(`.claude/rules/benchmarks.md`)."""

from collections.abc import Sequence

from strom_tools.commands import command_line
from strom_tools.workspace import git_files
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    command_line.parser(__doc__).parse_args(argv)
    print(git_files.commit_of_working_tree(this_repository()))
    return 0
