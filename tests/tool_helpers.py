"""Helpers of the tool tests (`tests/tools/`): files and commits in a repository, a Makefile whose targets
record their calls, transcripts."""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import ModuleType

import pytest

from strom_tools.workspace.repository import Repository

MAKEFILE = """\
fix lint-python lint-docs:
\t@echo "$@ FILES=$(FILES) ARGS=$(ARGS)" >> make.log
\t@if [ -e $@.fails ]; then cat $@.fails; exit 1; fi
passes:
\t@echo fine
fails:
\t@echo broken; echo on stderr >&2; exit 1
"""
"""The targets the tools run: each appends its call to `make.log` and fails with the contents of
`<target>.fails`, if that file exists."""


def git(repository: Repository, *arguments: str) -> str:
    done = subprocess.run(["git", *arguments], cwd=repository.root, check=True, capture_output=True, text=True)
    return done.stdout.strip()


def write(repository: Repository, name: str, text: str = "") -> Path:
    path = repository.root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def commit(repository: Repository) -> str:
    """Commits every file git sees; the commit's id."""
    git(repository, "add", "--all")
    git(repository, "commit", "--quiet", "--message", "a commit")
    return git(repository, "rev-parse", "HEAD")


def with_makefile(repository: Repository) -> None:
    """Commits `MAKEFILE`, with what its targets write ignored."""
    write(repository, "Makefile", MAKEFILE)
    write(repository, ".gitignore", "make.log\n*.fails\n.checks/\n")
    commit(repository)


def make_calls(repository: Repository) -> list[str]:
    """The calls of the `MAKEFILE` targets so far."""
    log = repository.root / "make.log"
    return log.read_text().splitlines() if log.exists() else []


BENCHMARK = """\
import pytest

import strom


@pytest.mark.benchmark(group="cost")
def test_cost(benchmark):
    benchmark.extra_info["us_per_input"] = strom.COST
    benchmark(sum, [1, 2, 3])
"""
"""A benchmark whose metric `us_per_input` is a constant of the library it runs with: which copy that was, the
comparison of two revisions shows without a timing."""
QUICK_BENCHMARK = ["--benchmark-min-rounds=1", "--benchmark-max-time=0.01", "--benchmark-warmup=off"]


def with_benchmark(repository: Repository) -> None:
    """Commits a library with `COST = 1.0` and `BENCHMARK`, then sets `COST = 3.0` in the working tree."""
    write(repository, "src/strom/__init__.py", "COST = 1.0\n")
    write(repository, "benchmarks/benchmark.py", BENCHMARK)
    commit(repository)
    write(repository, "src/strom/__init__.py", "COST = 3.0\n")


def run_command(
    command: ModuleType, arguments: Sequence[str], repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> int:
    """Runs a command of `strom_tools.commands` on `repository` instead of on the one that holds the tools."""
    monkeypatch.setattr(command, "this_repository", lambda: repository)
    main: Callable[[Sequence[str]], int] = command.main
    return main(arguments)


def write_transcript(path: Path, records: Sequence[object]) -> Path:
    path.write_text("".join(f"{json.dumps(record)}\n" for record in records), encoding="utf-8")
    return path


def user_record(content: object, at: str | None = None, **more: object) -> dict[str, object]:
    """A record of a transcript with a message of the user: a text, or a list of blocks (`tool_result`)."""
    return {"type": "user", "timestamp": at, "message": {"content": content}, **more}


def assistant_record(*blocks: object, at: str | None = None, **message: object) -> dict[str, object]:
    """A record with a message of Claude: its blocks (`tool_use`), and what else the message holds (`usage`)."""
    return {"type": "assistant", "timestamp": at, "message": {"content": list(blocks), **message}}


def tool_use(tool_id: str, name: str, **tool_input: object) -> dict[str, object]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": tool_input}


def tool_result(tool_id: str, text: str, *, is_error: bool = False) -> dict[str, object]:
    return {"type": "tool_result", "tool_use_id": tool_id, "content": text, "is_error": is_error}


def api_answer(
    message_id: str, *, read: int = 0, output: int = 0, written: int = 0, for_an_hour: int = 0, model: str = "claude"
) -> dict[str, object]:
    """The record of Claude's answer to a request, charged 2 input tokens beside the given ones."""
    usage = {
        "input_tokens": 2,
        "cache_creation_input_tokens": written + for_an_hour,
        "cache_read_input_tokens": read,
        "output_tokens": output,
        "cache_creation": {"ephemeral_1h_input_tokens": for_an_hour, "ephemeral_5m_input_tokens": written},
    }
    return assistant_record(id=message_id, model=model, usage=usage)


TOOLS = Path(__file__).resolve().parents[1] / "tools"


def imported_after(*statements: str) -> set[str]:
    """The modules a fresh interpreter has imported after `statements`, as the hook command's is: the hook
    command runs at every tool call, and an import costs milliseconds (`python3 -X importtime`)."""
    script = [*statements, "import sys", "print(*sys.modules)"]
    env = {**os.environ, "PYTHONPATH": str(TOOLS)}
    run = subprocess.run([sys.executable, "-c", "\n".join(script)], capture_output=True, text=True, env=env, check=True)
    return set(run.stdout.split())
