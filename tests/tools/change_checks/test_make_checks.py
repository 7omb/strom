import re

from tool_helpers import with_makefile

from strom_tools.change_checks.make_checks import TARGETS, TargetRun, run_targets, summary
from strom_tools.workspace.repository import Repository


def test_every_target_runs_also_after_a_failure(repository: Repository) -> None:
    with_makefile(repository)
    runs = list(run_targets(repository, ["fails", "passes"]))
    assert [(run.target, run.passed) for run in runs] == [("fails", False), ("passes", True)]
    assert "broken\n" in runs[0].output and "on stderr\n" in runs[0].output
    assert runs[1].output == "fine\n"


def test_the_summary_is_one_line_with_the_last_line_of_the_output() -> None:
    passed = TargetRun("test", True, 12.34, "collected\n\n494 passed in 11.57s\n")
    assert re.fullmatch(r"test      ok       12\.3s  494 passed in 11\.57s", summary(passed))
    failed = TargetRun("lint", False, 0.5, "a.py:1: E501\nmake: *** [Makefile:40: lint-python] Error 1\n")
    assert summary(failed) == "lint      FAILED    0.5s  a.py:1: E501", "make's own line is no result"
    assert summary(TargetRun("type", True, 1.0, "")).rstrip() == "type      ok        1.0s"


def test_the_default_targets_are_those_of_make_check() -> None:
    assert TARGETS == ["lint", "type", "test", "examples"]
