import json
from pathlib import Path

import pytest

from strom_tools.change_checks.typing_diagnostics import (
    Checker,
    _mypy,
    _mypy_lines,
    _pyright_lines,
    _ty_lines,
    checker_of,
    diagnostics,
)
from strom_tools.tool_error import ToolError


def test_mypy_lines_keep_file_severity_and_message_without_the_position() -> None:
    output = (
        'src/a.py:12: error: Incompatible return value type (got "int", expected "str")  [return-value]\n'
        "src/a.py:12:5: note: See the docs\n"
        "tests/test_a.py:3:1: warning: unused ignore\n"
        "Found 1 error in 1 file (checked 3 source files)\n"
    )
    assert _mypy_lines(output) == [
        'mypy src/a.py: error: Incompatible return value type (got "int", expected "str")  [return-value]',
        "mypy src/a.py: note: See the docs",
        "mypy tests/test_a.py: warning: unused ignore",
    ]
    assert _mypy_lines("Success: no issues found in 3 source files\n") == []


def test_pyright_lines_have_the_file_from_the_root_and_the_message_on_one_line(tmp_path: Path) -> None:
    report = {
        "generalDiagnostics": [
            {
                "file": str(tmp_path / "src/a.py"),
                "severity": "error",
                "message": 'Type "int" is not assignable\n  "int" is not "str"',
                "rule": "reportReturnType",
            },
            {"file": str(tmp_path / "src/a.py"), "severity": "warning", "message": "no rule here"},
            {"file": str(tmp_path / "tests/a.py"), "severity": "information", "message": 'Type of "x" is "int"'},
        ]
    }
    assert _pyright_lines(json.dumps(report), tmp_path) == [
        'pyright src/a.py: error[reportReturnType]: Type "int" is not assignable / "int" is not "str"',
        "pyright src/a.py: warning[]: no rule here",
    ]


def test_ty_lines_keep_file_severity_rule_and_message() -> None:
    output = (
        "src/a.py:12:5: error[invalid-return-type] Return type does not match: expected `str`\n"
        "tests/a.py:3:1: warning[unused-ignore-comment] Unused `ty: ignore` directive\n"
        "tests/a.py:4:13: info[revealed-type] Revealed type: `int`\n"
        "Found 3 diagnostics\n"
    )
    assert _ty_lines(output) == [
        "ty src/a.py: error[invalid-return-type]: Return type does not match: expected `str`",
        "ty tests/a.py: warning[unused-ignore-comment]: Unused `ty: ignore` directive",
    ]


def test_a_checker_that_does_not_run_is_an_error_not_a_clean_result(tmp_path: Path) -> None:
    """mypy without a configuration and without files to check exits with 2."""
    with pytest.raises(ToolError, match=r"mypy did not run \(exit code 2\)"):
        _mypy(tmp_path)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project of one file for the three checkers, each with its options in `pyproject.toml`."""
    root = tmp_path / "project"
    root.mkdir()
    options = '[tool.mypy]\nfiles = ["wrong.py"]\n\n[tool.pyright]\ninclude = ["wrong.py"]\n'
    (root / "pyproject.toml").write_text(f'{options}\n[tool.ty.src]\ninclude = ["wrong.py"]\n')
    return root


def test_each_checker_reports_the_error_of_a_project(project: Path) -> None:
    """The checkers themselves run here: their output formats are theirs to change."""
    (project / "wrong.py").write_text("def name() -> str:\n    return 1\n")
    found = diagnostics(list(Checker), project)
    assert [line.split(": ", 2)[:2] for line in found] == [
        ["mypy wrong.py", "error"],
        ["pyright wrong.py", "error[reportReturnType]"],
        ["ty wrong.py", "error[invalid-return-type]"],
    ]
    assert [checker_of(line) for line in found] == list(Checker)
    assert diagnostics([Checker.TY], project) == found[2:], "only the checkers asked for"


def test_each_checker_reports_nothing_for_a_clean_project(project: Path) -> None:
    (project / "wrong.py").write_text('def name() -> str:\n    return "one"\n')
    assert diagnostics(list(Checker), project) == []


def test_a_line_names_its_checker_first() -> None:
    assert checker_of("pyright src/a.py: error[rule]: a message") is Checker.PYRIGHT
    assert checker_of("pylint src/a.py: error: a message") is None
