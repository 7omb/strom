"""Runs the make targets of `make check` and prints one line per target; a failing target's output in full.

Run:  python bin/check.py [TARGET ...]   (default: lint type test examples, the targets of `make check`)

All targets run, also after a failure, so one call shows every problem. A line holds the target, `ok` or
`FAILED`, its time and the last line of its output (e.g. pytest's counts); the full output follows only for
a failure. The exit code is 1 if any target failed. The commands stay in the Makefile, so this script and
`make check` don't drift apart.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ["lint", "type", "test", "examples"]


def main() -> int:
    failed = False
    for target in sys.argv[1:] or TARGETS:
        started_at = time.monotonic()
        result = subprocess.run(["make", "--no-print-directory", target], cwd=ROOT, capture_output=True, text=True)
        output = f"{result.stdout}{result.stderr}"
        lines = [line for line in output.splitlines() if line.strip() and not line.startswith("make: ")]
        status = "ok" if result.returncode == 0 else "FAILED"
        print(
            f"{target:9} {status:6} {time.monotonic() - started_at:6.1f}s  {lines[-1][:100] if lines else ''}",
            flush=True,
        )
        if result.returncode != 0:
            failed = True
            print(output)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
