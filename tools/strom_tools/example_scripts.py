"""The examples in `examples/`: each a uv script that runs in an environment of its own and checks its results.

What an example has to be, and how it is run and type-checked: `strom_tools.commands.run_examples`."""

import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

from strom_tools.json_objects import is_list, member
from strom_tools.tool_error import ToolError
from strom_tools.workspace.process_groups import run_detached
from strom_tools.workspace.repository import Repository

_TIMEOUT = 120.0  # seconds per example (the first run of a script also installs its environment)
_TIMEOUTS: dict[str, float] = {}  # per example (file name), where the default does not fit
OK = "ok"
"""The outcome of an example that ran, or type-checked, as expected."""
_SCRIPT_BLOCK = re.compile(r"(?m)^# /// script$\s(?P<content>(^#(| .*)$\s)+)^# ///$")  # PEP 723's own regex
_LOCK_COMMAND = "python bin/run_examples.py --lock"


def examples(repository: Repository, names: list[str]) -> list[Path]:
    """The examples to run: all (every `examples/*.py` whose name does not start with `_`), or the named ones
    (`simple` or `simple.py`; an unknown name is a `ToolError`)."""
    directory = repository.root / "examples"
    every = {path.name: path for path in sorted(directory.glob("*.py")) if not path.name.startswith("_")}
    if not names:
        return list(every.values())
    wanted = [name if name.endswith(".py") else f"{name}.py" for name in names]
    unknown = [name for name in wanted if name not in every]
    if unknown:
        raise ToolError(f"unknown examples: {', '.join(unknown)} (known: {', '.join(every)})")
    return [every[name] for name in wanted]


def _dependencies(example: Path) -> list[str]:
    """The dependencies its script header declares; a `ToolError` if it has no header (every example is a uv
    script)."""
    match = _SCRIPT_BLOCK.search(example.read_text(encoding="utf-8"))
    if match is None:
        raise ToolError(f"{example.name}: no `# /// script` header (see `bin/run_examples.py --help`)")
    block: str = match["content"]
    content = "".join(line[2:] if line.startswith("# ") else line[1:] for line in block.splitlines(True))
    header: object = tomllib.loads(content)
    declared = member(header, "dependencies")
    return [str(dependency) for dependency in declared] if is_list(declared) else []


def run(example: Path) -> tuple[str, str, str]:
    """Runs one example; its outcome (`OK`, a stale lock, `exit code N` or `timeout after N s`), stdout and
    stderr."""
    if (stale := _stale_lock(example)) is not None:
        return stale, "", ""
    command = ["uv", "run", "--script", "--locked", "--quiet", "--python", sys.executable, str(example)]
    timeout = _TIMEOUTS.get(example.name, _TIMEOUT)
    with tempfile.TemporaryDirectory() as cwd:
        ran = run_detached(command, cwd=Path(cwd), timeout=timeout)
    if ran.returncode is None:
        return f"timeout after {timeout:g} s", ran.stdout, ran.stderr
    return (OK if ran.returncode == 0 else f"exit code {ran.returncode}"), ran.stdout, ran.stderr


def _stale_lock(example: Path) -> str | None:
    """None if the example's lock file fits its header (and strom's `pyproject.toml`, whose dependency groups it
    records), else the outcome that says how to update it. A `ToolError` for an example without a header."""
    _dependencies(example)
    check = subprocess.run(["uv", "lock", "--script", str(example), "--check", "--quiet"], capture_output=True)
    return None if check.returncode == 0 else f"stale lock {example.name}.lock (update: {_LOCK_COMMAND})"


def lock(example: Path) -> None:
    """Updates the lock file of an example (`uv lock --script`)."""
    _dependencies(example)
    subprocess.run(["uv", "lock", "--script", str(example)], check=True)


def check_types(repository: Repository, example: Path) -> tuple[str, str, str]:
    """mypy, pyright and ty on one example, with the options of the repository's `pyproject.toml` against its
    script's environment; `OK` or the tools that failed, their output, and nothing for stderr."""
    if (stale := _stale_lock(example)) is not None:
        return stale, "", ""
    subprocess.run(
        ["uv", "sync", "--script", str(example), "--locked", "--quiet", "--python", sys.executable], check=True
    )
    python_of = ["uv", "python", "find", "--script", str(example)]  # the environment `uv sync` just made
    python = subprocess.run(python_of, check=True, capture_output=True, text=True).stdout.strip()
    environment = Path(python).parent.parent
    failed: list[str] = []
    output = ""
    with tempfile.TemporaryDirectory() as config_dir:
        # pyright's `venv` in pyproject.toml outranks `--pythonpath`: a config of its own names the environment
        pyright_config = Path(config_dir) / "pyrightconfig.json"
        config: dict[str, str] = {
            "pythonVersion": "3.14",
            "venvPath": str(environment.parent),
            "venv": environment.name,
        }
        pyright_config.write_text(json.dumps(config))
        tools = {
            "mypy": [sys.executable, "-m", "mypy", "--no-pretty", "--python-executable", python, str(example)],
            "pyright": ["pyright", "--project", str(pyright_config), str(example)],
            "ty": ["ty", "check", "--python", python, str(example)],
        }
        for tool, command in tools.items():
            result = subprocess.run(command, cwd=repository.root, capture_output=True, text=True)
            if result.returncode != 0:
                failed.append(tool)
                output += f"--- {tool}\n{result.stdout}{result.stderr}"
    return (OK if not failed else f"type errors ({', '.join(failed)})"), output, ""
