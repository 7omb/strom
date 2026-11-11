"""Runs the tests against a copy of the code with an injected bug, to check that they catch it (skill
`validate-change`).

Run:  python bin/mutant.py --replace FILE OLD NEW [--tests-from REV] [--timeout S] [-- PYTEST_ARGS]
      python bin/mutant.py --patch PATCH [--tests-from REV] [--timeout S] [-- PYTEST_ARGS]

  --replace FILE OLD NEW  the bug: OLD, which must occur exactly once in FILE (a path such as
                          `src/strom/_interpreters/streaming.py`), replaced by NEW
  --patch PATCH           the bug as a patch file (`git diff` format, paths relative to the repository root)
  --tests-from REV        the tests of a revision (e.g. HEAD: the old tests; `:index`: the staged ones) instead
                          of the working tree's
  PYTEST_ARGS             e.g. `-k concurrency_limit` (default: the whole suite, stopping at the first failure)

The tests run on a copy of the code in a temporary directory, first without the bug, then with it; after
`--timeout` seconds a run is killed, pool workers included (injected bugs often hang). Nothing in the repository
changes. What is copied and how a run is isolated: `strom_tools.change_checks.mutants`.

Outcome and exit code: `caught` (a test failed: 0), `missed` (all passed: 1), `hung` (timeout: 2), or 3 if the
tests do not pass without the bug or pytest ended otherwise (e.g. a collection error); 4 if the script itself
did not run (wrong arguments, an OLD that does not occur once). Run the old and the new tests: a new test should
catch a bug the old ones miss.
"""

import tempfile
from collections.abc import Sequence
from pathlib import Path

from strom_tools.change_checks.mutants import Bug, Patch, Replace, Verdict, ended, failed_tests, try_bug, verdict
from strom_tools.change_checks.revisions import WORKING_TREE, parse
from strom_tools.commands import command_line
from strom_tools.workspace.processes import ProcessRun
from strom_tools.workspace.repository import this_repository

_EXIT_CODES = {Verdict.CAUGHT: 0, Verdict.MISSED: 1, Verdict.HUNG: 2, Verdict.UNDECIDED: 3}


def main(argv: Sequence[str]) -> int:
    own, pytest_args = command_line.split_passthrough(argv)
    parser = command_line.parser(__doc__)
    kind = parser.add_mutually_exclusive_group(required=True)
    kind.add_argument("--replace", nargs=3, metavar=("FILE", "OLD", "NEW"))
    kind.add_argument("--patch", metavar="PATCH")
    parser.add_argument("--tests-from", default=WORKING_TREE, metavar="REV", help="default: the working tree")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds (default: 300)")
    args = parser.parse_args(own)
    replace: list[str] | None = args.replace
    patch: str | None = args.patch
    tests_from: str = args.tests_from
    timeout: float = args.timeout
    if replace is not None:
        bug: Bug = Replace(*replace)
    elif patch is not None:
        bug = Patch(Path(patch))
    else:  # argparse requires one of them
        parser.error("one of --replace and --patch is required")
    command_line.require_modules("pytest")
    repository = this_repository()
    with tempfile.TemporaryDirectory(prefix="strom-mutant-") as tmp:
        trial = try_bug(repository, bug, parse(repository, tests_from), pytest_args, timeout, Path(tmp))
    found = verdict(trial)
    if trial.mutant is None:
        print(_output(trial.clean), end="")
        print(f"the tests of {tests_from} do not pass without the bug ({ended(trial.clean)}): no verdict")
        return _EXIT_CODES[found]
    print("\n".join(failed_tests(trial.mutant)))
    match found:
        case Verdict.CAUGHT:
            print(f"caught: a test failed (tests of {tests_from})")
        case Verdict.MISSED:
            print(f"missed: every test passed (tests of {tests_from})")
        case Verdict.HUNG:
            print(f"hung: killed after {timeout:g} s (tests of {tests_from}); narrow it with -k")
        case Verdict.UNDECIDED:
            print(f"{_output(trial.mutant)}pytest exit code {trial.mutant.returncode}", end="")
    return _EXIT_CODES[found]


def _output(run: ProcessRun) -> str:
    return f"--- stdout\n{run.stdout}--- stderr\n{run.stderr}"
