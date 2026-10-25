"""Runs the tests against a library copy with an injected bug, to check that they catch it (skill `validate-change`).

Run:  python bin/mutant.py --replace FILE OLD NEW [--tests-from REV] [--timeout S] [-- PYTEST_ARGS]
      python bin/mutant.py --patch PATCH [--tests-from REV] [--timeout S] [-- PYTEST_ARGS]

  --replace FILE OLD NEW  the bug: OLD, which must occur exactly once in FILE (a path such as
                          `src/strom/_interpreters/streaming.py`), replaced by NEW
  --patch PATCH           the bug as a patch file (`git diff` format, paths relative to the repository root)
  --tests-from REV        the tests of a revision (e.g. HEAD: the old tests; `:index`: the staged ones) instead
                          of the working tree's
  PYTEST_ARGS             e.g. `-k concurrency_limit` (default: the whole suite, stopping at the first failure)

The library (`src/` of the working tree), the tests and `pyproject.toml` are copied into a temporary
directory, the bug is injected into the copy and pytest runs there, with the copy first on PYTHONPATH (it is
checked that `import strom` finds it) and in its own process group: injected bugs often hang (a join
waiting forever), so after `--timeout` seconds the whole group is killed, pool workers included. Nothing in
the repository changes, also not its caches or Hypothesis database.

The same tests run on the copy without the bug first: they must pass there, so that a failure means the
bug was caught (not a test that fails anyway, nor a missing pytest). Outcome and exit code: `caught` (a
test failed: 0), `missed` (all passed: 1), `hung` (timeout: 2), or 3 if the tests do not pass without the
bug or pytest ended otherwise (e.g. a collection error). Run the old and the new tests: a new test should
catch a bug the old ones miss.
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from _tools import WORKING_TREE, export, library_copy, python_path_env, require_modules, run_detached, split_passthrough

DEFAULT_PYTEST_ARGS = ["-x", "-q"]


def inject(copy: Path, args: argparse.Namespace) -> None:
    """Injects the bug of `args` into the copy of the repository at `copy`."""
    if args.patch is not None:
        subprocess.run(["git", "apply", str(Path(args.patch).resolve())], cwd=copy, check=True)
        return
    file, old, new = args.replace
    target = copy / file
    text = target.read_text()
    if text.count(old) != 1:
        sys.exit(f"OLD occurs {text.count(old)} times in {file}, not once")
    target.write_text(text.replace(old, new))


def main() -> int:
    own, pytest_args = split_passthrough(sys.argv[1:])
    parser = argparse.ArgumentParser(description="Runs the tests against a library with an injected bug.")
    bug = parser.add_mutually_exclusive_group(required=True)
    bug.add_argument("--replace", nargs=3, metavar=("FILE", "OLD", "NEW"))
    bug.add_argument("--patch", metavar="PATCH")
    parser.add_argument("--tests-from", default=WORKING_TREE, metavar="REV", help="default: the working tree")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds (default: 300)")
    args = parser.parse_args(own)
    require_modules("pytest")
    command = [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *(pytest_args or DEFAULT_PYTEST_ARGS)]
    with tempfile.TemporaryDirectory(prefix="strom-mutant-") as tmp:
        copy = Path(tmp)
        src = library_copy(WORKING_TREE, copy)
        export(args.tests_from, ["tests", "pyproject.toml"], copy)
        env = python_path_env(src)
        returncode, stdout, stderr = run_detached(command, cwd=copy, timeout=args.timeout, env=env)
        if returncode != 0:
            outcome = "hung" if returncode is None else f"exit code {returncode}"
            print(f"--- stdout\n{stdout}--- stderr\n{stderr}", end="")
            print(f"the tests of {args.tests_from} do not pass without the bug ({outcome}): no verdict")
            return 3
        inject(copy, args)
        returncode, stdout, stderr = run_detached(command, cwd=copy, timeout=args.timeout, env=env)
    print("\n".join(line for line in stdout.splitlines() if line.startswith(("FAILED", "ERROR"))))
    if returncode == 1:
        print(f"caught: a test failed (tests of {args.tests_from})")
        return 0
    if returncode == 0:
        print(f"missed: every test passed (tests of {args.tests_from})")
        return 1
    if returncode is None:
        print(f"hung: killed after {args.timeout:g} s (tests of {args.tests_from}); narrow it with -k")
        return 2
    print(f"--- stdout\n{stdout}--- stderr\n{stderr}pytest exit code {returncode}", end="")
    return 3


if __name__ == "__main__":
    sys.exit(main())
