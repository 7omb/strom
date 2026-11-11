"""What the commands share: running one as a script, its parser, the arguments it passes on, and the exit code
of a command that did not run."""

import argparse
import importlib.util
import sys
import traceback
from collections.abc import Callable, Sequence
from typing import NoReturn, override

from strom_tools.tool_error import ToolError

DID_NOT_RUN = 4
"""The exit code of a command that could not do what it was asked: wrong arguments, a `ToolError`, an exception.
No command uses it for an outcome (0 and 1 are outcomes everywhere, 2 and 3 verdicts of `mutant`), so "the tests
missed the bug" or "the diagnostics differ" is never read off a command that failed."""


def run(main: Callable[[Sequence[str]], int]) -> int:
    """Runs a command with this process's arguments; its exit code, or `DID_NOT_RUN` after printing the
    `ToolError` that ended it, or the traceback of another exception."""
    try:
        return main(sys.argv[1:])
    except ToolError as error:
        print(error, file=sys.stderr)
        return DID_NOT_RUN
    except Exception:  # a bug: as Python reports it, but not with exit code 1, an outcome
        traceback.print_exc()
        return DID_NOT_RUN


class _Parser(argparse.ArgumentParser):
    """A parser whose usage errors exit with `DID_NOT_RUN` (argparse: 2); its subparsers are of this class too."""

    @override
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(DID_NOT_RUN, f"{self.prog}: error: {message}\n")


def parser(usage: str | None) -> argparse.ArgumentParser:
    """A parser whose `--help` shows `usage` as written: the docstring of the command's module."""
    return _Parser(description=usage, formatter_class=argparse.RawDescriptionHelpFormatter)


def split_passthrough(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """The command's own arguments and those after `--` (passed on to pytest)."""
    if "--" not in argv:
        return list(argv), []
    at = list(argv).index("--")
    return list(argv[:at]), list(argv[at + 1 :])


def require_modules(*names: str) -> None:
    """A `ToolError` unless this interpreter has the modules: a missing one would look like failing tests."""
    missing = [name for name in names if importlib.util.find_spec(name) is None]
    if missing:
        raise ToolError(
            f"{', '.join(missing)} not installed for {sys.executable}: run with `uv run --frozen python bin/...`"
        )
