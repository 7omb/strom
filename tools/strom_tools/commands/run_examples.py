"""Runs the examples in `examples/`, each as a uv script in an environment of its own, and reports which ones
failed; or type-checks them there.

Run:  python bin/run_examples.py [NAME ...]           all examples, or those named (`simple` or `simple.py`)
      python bin/run_examples.py --type [NAME ...]    mypy, pyright and ty on each, in its environment
      python bin/run_examples.py --lock [NAME ...]    updates their lock files (`uv lock --script`)
      make examples                                  all examples (also part of `make check` and tox)

The examples are reference code for users, not part of the test suite; this runner keeps them correct.
Every `examples/*.py` whose name does not start with `_` is an example (`_` files are shared helpers).

An example
  * is a uv script (PEP 723): a `# /// script` header declares its dependencies, strom as an editable path
    source (`strom = { path = "..", editable = true }` under `[tool.uv.sources]`), and `<name>.py.lock`
    next to it pins them (`--lock`). So examples need no dependency of the dev environment, and two
    examples may need different versions of one package. The lock also records strom's dependency groups:
    after a change to them, `--lock` again (a stale lock fails the run with that hint);
  * is a script with an `if __name__ == "__main__":` guard (the process backend imports it again);
  * checks its own results (counts, contents; never timings: they depend on the machine) and exits with
    0 if all are as expected, else with 1 (`sys.exit(main())`);
  * reports each wrong result as one line on stderr, saying what was expected and what it got, e.g.
    `FAILED collected scores (thread backend): expected 40, got 38`, and reports all of them before
    exiting; it does not `assert` (removed by `python -O`) and does not catch exceptions to exit with 1
    (the traceback is the better message: an uncaught exception exits with 1 as well);
  * runs within `_TIMEOUT` seconds (or its entry in `_TIMEOUTS`, both in `strom_tools.example_scripts`) on a
    slow machine.

Each example runs with `uv run --script --locked` on this interpreter's Python (3.14 or 3.14t), in a temporary
working directory, in its own process group: on a timeout the whole group is killed, pool workers included.
POSIX only (`start_new_session`, `killpg`).

`--type` checks each example with the options of `pyproject.toml` against the environment of its script
(`uv python find --script`): mypy from this interpreter, pyright and ty from PATH. The checks of `make type`
leave `examples/` out, as the dev environment does not have their dependencies.
"""

import sys
import time
from collections.abc import Sequence

from strom_tools import example_scripts
from strom_tools.commands import command_line
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    parser = command_line.parser(__doc__)
    parser.add_argument("names", nargs="*", help="examples to run (default: all)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--type", action="store_true", help="type-check them instead, each in its environment")
    mode.add_argument("--lock", action="store_true", help="update their lock files (`uv lock --script`)")
    args = parser.parse_args(argv)
    names: list[str] = args.names
    check_types: bool = args.type
    lock: bool = args.lock
    repository = this_repository()
    examples = example_scripts.examples(repository, names)
    if lock:
        for example in examples:
            example_scripts.lock(example)
        return 0
    failed: list[str] = []
    for example in examples:
        started_at = time.perf_counter()
        outcome = example_scripts.check_types(repository, example) if check_types else example_scripts.run(example)
        run_time = time.perf_counter() - started_at
        print(f"{example.name}: {example_scripts.described(outcome)} ({run_time:.1f} s)", flush=True)
        if not isinstance(outcome, example_scripts.Passed):
            failed.append(example.name)
            print(example_scripts.shown_output(outcome), end="", flush=True)
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0
