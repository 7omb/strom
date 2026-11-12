from collections.abc import Sequence

import pytest

from strom_tools.commands import mutant
from strom_tools.commands.command_line import DID_NOT_RUN, parser, require_modules, run, split_passthrough
from strom_tools.tool_error import ToolError


def test_run_passes_the_arguments_and_returns_the_exit_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sys.argv", ["bin/tool.py", "diff", "--name", "x"])
    seen: list[Sequence[str]] = []

    def main(argv: Sequence[str]) -> int:
        seen.append(argv)
        return 3

    assert run(main) == 3
    assert seen == [["diff", "--name", "x"]]


def test_a_tool_error_is_printed_and_the_command_did_not_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def main(argv: Sequence[str]) -> int:
        raise ToolError("no revision nowhere")

    monkeypatch.setattr("sys.argv", ["bin/tool.py"])
    assert run(main) == DID_NOT_RUN
    assert capsys.readouterr() == ("", "no revision nowhere\n")


def test_another_exception_is_printed_with_its_traceback_and_the_command_did_not_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def main(argv: Sequence[str]) -> int:
        raise ValueError("a bug")

    monkeypatch.setattr("sys.argv", ["bin/tool.py"])
    assert run(main) == DID_NOT_RUN
    reported = capsys.readouterr().err
    assert reported.startswith("Traceback (most recent call last):") and reported.endswith("ValueError: a bug\n")


def test_a_usage_error_exits_with_did_not_run_also_in_a_subparser(capsys: pytest.CaptureFixture[str]) -> None:
    made = parser("Does a thing.")
    made.add_argument("--runs", type=int)
    listing = made.add_subparsers(dest="action", required=True).add_parser("list")
    listing.add_argument("-n", type=int)
    for arguments in (["--runs", "many", "list"], [], ["list", "-n", "few"], ["forget"]):
        with pytest.raises(SystemExit) as exited:
            made.parse_args(arguments)
        assert exited.value.code == DID_NOT_RUN, arguments
        assert ": error: " in capsys.readouterr().err
    with pytest.raises(SystemExit) as exited:
        made.error("RUNS must be >= 1")
    assert exited.value.code == DID_NOT_RUN
    assert capsys.readouterr().err.endswith(": error: RUNS must be >= 1\n")


def test_did_not_run_is_no_outcome_of_a_command() -> None:
    """0 and 1 are outcomes of every command, and `mutant` has a verdict for each code up to 3."""
    assert DID_NOT_RUN not in {0, 1, *mutant._EXIT_CODES.values()}


def test_the_arguments_after_two_dashes_are_passed_on() -> None:
    assert split_passthrough(["HEAD", "-n", "3", "--", "-k", "pools", "--", "x"]) == (
        ["HEAD", "-n", "3"],
        ["-k", "pools", "--", "x"],
    )
    assert split_passthrough(["HEAD"]) == (["HEAD"], [])
    assert split_passthrough(["--"]) == ([], [])


def test_help_shows_the_usage_as_written(capsys: pytest.CaptureFixture[str]) -> None:
    usage = "Does a thing.\n\nRun:  python bin/thing.py [NAME]\n\n  NAME   what to do it to\n"
    with pytest.raises(SystemExit) as exited:
        parser(usage).parse_args(["--help"])
    assert exited.value.code == 0
    assert usage in capsys.readouterr().out


def test_a_missing_module_is_an_error_before_it_looks_like_failing_tests() -> None:
    require_modules("json", "pytest")
    with pytest.raises(ToolError, match=r"no_such_module_a, no_such_module_b not installed for .*: run with `uv run"):
        require_modules("json", "no_such_module_a", "no_such_module_b")
