"""Saves or compares the test IDs pytest collects, for restructuring tests (skill `validate-change`).

Run:  python bin/collect_ids.py save [--name NAME] [-- PYTEST_ARGS]   writes .checks/collect-ids-NAME.txt
      python bin/collect_ids.py diff [--name NAME] [-- PYTEST_ARGS]   compares the current IDs with it
      python bin/collect_ids.py diff --against REV [-- PYTEST_ARGS]   compares them with those of REV

NAME defaults to `before`; PYTEST_ARGS select what is collected (default: `testpaths`). `--against` needs
no snapshot: it collects in a copy of REV (e.g. HEAD, main~2, `:index` for the staged changes) in a temporary
directory, with REV's library first on PYTHONPATH. `diff` lists the removed (`-`) and added (`+`) IDs and
exits with 1 if there are any: explain every difference.
"""

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from subprocess import PIPE

from _tools import (
    ROOT,
    SNAPSHOTS,
    checkout,
    diff,
    python_path_env,
    require_modules,
    save_or_diff,
    split_passthrough,
)


def collected(pytest_args: list[str], root: Path = ROOT, env: Mapping[str, str] | None = None) -> list[str]:
    """The IDs of the tests that `pytest --collect-only` finds in `root`."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *pytest_args],
        cwd=root,
        env=env,
        stdout=PIPE,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"collection failed (exit code {result.returncode}):\n{result.stdout}")
    return [line for line in result.stdout.splitlines() if "::" in line]


def main() -> int:
    own, pytest_args = split_passthrough(sys.argv[1:])
    parser = argparse.ArgumentParser(description="Saves or compares the collected test IDs.")
    parser.add_argument("action", choices=["save", "diff"])
    parser.add_argument("--name", default="before", help="name of the snapshot (default: before)")
    parser.add_argument("--against", metavar="REV", help="diff: compare with revision REV instead of a snapshot")
    args = parser.parse_args(own)
    if args.against is not None and args.action != "diff":
        parser.error("--against needs `diff`")
    require_modules("pytest")
    if args.against is not None:
        revision: str = args.against
        with tempfile.TemporaryDirectory(prefix="strom-ids-") as tmp:
            copy = checkout(revision, Path(tmp))
            before = collected(pytest_args, copy, python_path_env(copy / "src"))
        return diff(before, collected(pytest_args), "IDs", f"in {revision}")
    return save_or_diff(args.action, SNAPSHOTS / f"collect-ids-{args.name}.txt", collected(pytest_args), "IDs")


if __name__ == "__main__":
    sys.exit(main())
