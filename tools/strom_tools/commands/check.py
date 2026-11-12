"""Runs the make targets of `make check` and prints one line per target; a failing target's output in full.

Run:  python bin/check.py [TARGET ...]   (default: lint type cov examples, the targets of `make check`)

All targets run, also after a failure, so one call shows every problem. A line holds the target, `ok` or
`FAILED`, its time and the last line of its output (e.g. pytest's counts); the full output follows only for
a failure. The exit code is 1 if any target failed. The commands stay in the Makefile, so this script and
`make check` don't drift apart.
"""

from collections.abc import Sequence

from strom_tools.change_checks.make_checks import TARGETS, run_targets, summary
from strom_tools.commands import command_line
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("targets", nargs="*", metavar="TARGET", help="default: the targets of `make check`")
    args = parser.parse_args(argv)
    targets: list[str] = args.targets
    failed = False
    for run in run_targets(this_repository(), targets or TARGETS):
        print(summary(run), flush=True)
        if not run.passed:
            failed = True
            print(run.output)
    return 1 if failed else 0
