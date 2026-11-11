from tool_helpers import make_calls, with_makefile, write

from strom_tools.workspace.make_runs import problems, run_make
from strom_tools.workspace.processes import output
from strom_tools.workspace.repository import Repository


def test_a_passing_target_has_no_problems(repository: Repository) -> None:
    with_makefile(repository)
    run = run_make(repository, "passes")
    assert (run.returncode, run.stdout, run.stderr) == (0, "fine\n", "")
    assert problems(run) == ""


def test_a_failing_target_reports_its_output_with_makes_own_line(repository: Repository) -> None:
    with_makefile(repository)
    run = run_make(repository, "fails")
    assert run.returncode != 0 and run.stdout == "broken\n"
    assert run.stderr.startswith("on stderr\nmake: *** ")
    assert problems(run) == output(run) == run.stdout + run.stderr


def test_targets_and_variables_are_passed_on(repository: Repository) -> None:
    with_makefile(repository)
    run_make(repository, "fix", "lint-python", "FILES=a.py b.py", "ARGS=--select I")
    assert make_calls(repository) == [
        "fix FILES=a.py b.py ARGS=--select I",
        "lint-python FILES=a.py b.py ARGS=--select I",
    ]


def test_recipes_are_echoed_unless_silent(repository: Repository) -> None:
    write(repository, "Makefile", "shown:\n\ttrue\n")
    assert run_make(repository, "shown").stdout == ""
    assert run_make(repository, "shown", silent=False).stdout == "true\n"
