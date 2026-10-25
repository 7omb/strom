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
  * runs within `TIMEOUT` seconds (or its entry in `TIMEOUTS`) on a slow machine.

Each example runs with `uv run --script --locked` on this interpreter's Python (3.14 or 3.14t), in a temporary
working directory, in its own process group: on a timeout the whole group is killed, pool workers included.
POSIX only (`start_new_session`, `killpg`).

`--type` checks each example with the options of `pyproject.toml` against the environment of its script
(`uv python find --script`): mypy from this interpreter, pyright and ty from PATH. The checks of `make type`
leave `examples/` out, as the dev environment does not have their dependencies.
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from _tools import ROOT, run_detached

EXAMPLES = ROOT / "examples"
TIMEOUT = 120.0  # seconds per example (the first run of a script also installs its environment)
TIMEOUTS: dict[str, float] = {}  # per example (file name), where the default does not fit
_SCRIPT_BLOCK = re.compile(r"(?m)^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$")  # PEP 723's own regex


def examples(names: list[str]) -> list[Path]:
    """The examples to run: all, or the named ones (an unknown name is an error)."""
    every = {path.name: path for path in sorted(EXAMPLES.glob("*.py")) if not path.name.startswith("_")}
    if not names:
        return list(every.values())
    wanted = [name if name.endswith(".py") else f"{name}.py" for name in names]
    unknown = [name for name in wanted if name not in every]
    if unknown:
        sys.exit(f"unknown examples: {', '.join(unknown)} (known: {', '.join(every)})")
    return [every[name] for name in wanted]


def dependencies(example: Path) -> list[str]:
    """The dependencies its script header declares; exits if it has none (every example is a uv script)."""
    match = _SCRIPT_BLOCK.search(example.read_text(encoding="utf-8"))
    if match is None:
        sys.exit(f"{example.name}: no `# /// script` header (see the docstring of {Path(__file__).name})")
    content = "".join(line[2:] if line.startswith("# ") else line[1:] for line in match["content"].splitlines(True))
    declared: list[str] = tomllib.loads(content).get("dependencies", [])
    return declared


def run(example: Path) -> tuple[str, str, str]:
    """Runs one example; its outcome (`ok`, a stale lock, `exit code N` or `timeout after N s`), stdout and
    stderr."""
    if (stale := _stale_lock(example)) is not None:
        return stale, "", ""
    command = ["uv", "run", "--script", "--locked", "--quiet", "--python", sys.executable, str(example)]
    timeout = TIMEOUTS.get(example.name, TIMEOUT)
    with tempfile.TemporaryDirectory() as cwd:
        returncode, stdout, stderr = run_detached(command, cwd=Path(cwd), timeout=timeout)
    if returncode is None:
        return f"timeout after {timeout:g} s", stdout, stderr
    return ("ok" if returncode == 0 else f"exit code {returncode}"), stdout, stderr


def _stale_lock(example: Path) -> str | None:
    """None if the example's lock file fits its header (and strom's `pyproject.toml`, whose dependency groups it
    records), else the outcome that says how to update it. Exits for an example without a header."""
    dependencies(example)
    check = subprocess.run(["uv", "lock", "--script", str(example), "--check", "--quiet"], capture_output=True)
    return None if check.returncode == 0 else f"stale lock {example.name}.lock (update: {_LOCK_COMMAND})"


_LOCK_COMMAND = "python bin/run_examples.py --lock"


def check_types(example: Path) -> tuple[str, str, str]:
    """mypy, pyright and ty on one example, against its script's environment; `ok` or the tools that failed."""
    if (stale := _stale_lock(example)) is not None:
        return stale, "", ""
    subprocess.run(
        ["uv", "sync", "--script", str(example), "--locked", "--quiet", "--python", sys.executable], check=True
    )
    python_of = ["uv", "python", "find", "--script", str(example)]  # the environment `uv sync` just made
    python = subprocess.run(python_of, check=True, capture_output=True, text=True).stdout.strip()
    environment = Path(python).parent.parent
    failed, output = [], ""
    with tempfile.TemporaryDirectory() as config_dir:
        # pyright's `venv` in pyproject.toml outranks `--pythonpath`: a config of its own names the environment
        pyright_config = Path(config_dir) / "pyrightconfig.json"
        pyright_config.write_text(
            json.dumps({"pythonVersion": "3.14", "venvPath": str(environment.parent), "venv": environment.name})
        )
        tools = {
            "mypy": [sys.executable, "-m", "mypy", "--no-pretty", "--python-executable", python, str(example)],
            "pyright": ["pyright", "--project", str(pyright_config), str(example)],
            "ty": ["ty", "check", "--python", python, str(example)],
        }
        for tool, command in tools.items():
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
            if result.returncode != 0:
                failed.append(tool)
                output += f"--- {tool}\n{result.stdout}{result.stderr}"
    return ("ok" if not failed else f"type errors ({', '.join(failed)})"), output, ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Runs the examples in examples/.")
    parser.add_argument("names", nargs="*", help="examples to run (default: all)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--type", action="store_true", help="type-check them instead, each in its environment")
    mode.add_argument("--lock", action="store_true", help="update their lock files (`uv lock --script`)")
    args = parser.parse_args()
    if args.lock:
        for example in examples(args.names):
            dependencies(example)
            subprocess.run(["uv", "lock", "--script", str(example)], check=True)
        return 0
    failed: list[str] = []
    for example in examples(args.names):
        started_at = time.perf_counter()
        outcome, stdout, stderr = check_types(example) if args.type else run(example)
        print(f"{example.name}: {outcome} ({time.perf_counter() - started_at:.1f} s)", flush=True)
        if outcome != "ok":
            failed.append(example.name)
            print(f"--- stdout\n{stdout}--- stderr\n{stderr}", end="", flush=True)
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
