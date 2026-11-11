"""The commands as a whole: each one's help, its usage errors, and the exit codes that differ from "0 or 1". What
each prints and exits with: the test modules beside this one (a module for the commands that have a kind of
outcome in common); `docs/decisions.md` (Tool package) says what only a real run covers."""

import importlib
from collections.abc import Callable, Sequence
from types import ModuleType

import pytest

from strom_tools.change_checks.mutants import Verdict
from strom_tools.commands import command_line, mutant

COMMANDS = [
    "ab",
    "check",
    "check_docs",
    "collect_ids",
    "mutant",
    "rename",
    "run_examples",
    "sessions",
    "typing_snapshot",
]


@pytest.mark.parametrize("name", COMMANDS)
def test_help_is_the_docstring_of_the_command(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    command: ModuleType = importlib.import_module(f"strom_tools.commands.{name}")
    main: Callable[[Sequence[str]], int] = command.main
    with pytest.raises(SystemExit) as exited:
        main(["--help"])
    assert exited.value.code == 0
    shown = capsys.readouterr().out
    assert command.__doc__ is not None and command.__doc__.strip() in shown
    assert f"python bin/{name}.py" in shown, "the usage names the script"


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("ab", ["HEAD", ".", "-n", "0"]),
        ("ab", ["--cpus", "fast"]),
        ("collect_ids", ["save", "--against", "HEAD"]),
        ("typing_snapshot", ["save", "--against", "HEAD"]),
        ("typing_snapshot", ["diff", "--tools", "pylint"]),
        ("mutant", []),
        ("mutant", ["--replace", "a.py", "old"]),
        ("mutant", ["--replace", "a.py", "old", "new", "--patch", "bug.patch"]),
        ("rename", ["only_one"]),
        ("run_examples", ["--type", "--lock"]),
        ("sessions", []),
        ("sessions", ["forget"]),
    ],
)
def test_wrong_arguments_are_a_usage_error(name: str, arguments: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    main: Callable[[Sequence[str]], int] = importlib.import_module(f"strom_tools.commands.{name}").main
    with pytest.raises(SystemExit) as exited:
        main(arguments)
    assert exited.value.code == command_line.DID_NOT_RUN
    assert ": error: " in capsys.readouterr().err


def test_a_verdict_of_mutant_has_its_exit_code() -> None:
    assert {verdict.value: code for verdict, code in mutant._EXIT_CODES.items()} == {
        "caught": 0,
        "missed": 1,
        "hung": 2,
        "no verdict": 3,
    }
    assert set(mutant._EXIT_CODES) == set(Verdict)
