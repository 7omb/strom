"""`check`, `mutant`, `run_examples` and `ab`: what they print and exit with for the outcomes of what they run."""

import os
from collections.abc import Sequence
from pathlib import Path

import pytest
from tool_helpers import QUICK_BENCHMARK, commit, run_command, with_benchmark, with_makefile, write

from strom_tools import example_scripts
from strom_tools.change_checks import benchmark_comparison
from strom_tools.change_checks.revisions import Commit, Revision, WorkingTree
from strom_tools.commands import ab, check, command_line, mutant, run_examples
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository


def test_check_prints_a_line_per_target_and_the_output_of_a_failed_one(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with_makefile(repository)
    assert run_command(check, ["passes"], repository, monkeypatch) == 0
    assert capsys.readouterr().out.split() == ["passes", "ok", "0.0s", "fine"]
    assert run_command(check, ["fails", "passes"], repository, monkeypatch) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split()[:2] == ["fails", "FAILED"] and lines[1:3] == ["broken", "on stderr"]
    assert lines[-1].split()[:2] == ["passes", "ok"], "it runs after the failure"


@pytest.fixture
def doubling(repository: Repository) -> Repository:
    write(repository, "src/strom/__init__.py", "def double(x: int) -> int:\n    return 2 * x\n")
    write(repository, "tests/test_double.py", "import strom\n\n\ndef test_double():\n    assert strom.double(2) == 4\n")
    write(repository, "pyproject.toml", '[tool.pytest.ini_options]\ntestpaths = ["tests"]\n')
    commit(repository)
    return repository


def test_mutant_reports_a_caught_bug_with_the_failed_tests(
    doubling: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    bug = ["--replace", "src/strom/__init__.py", "2 * x", "3 * x"]
    assert run_command(mutant, [*bug, "--", "-q"], doubling, monkeypatch) == 0
    assert capsys.readouterr().out.splitlines() == [
        "FAILED tests/test_double.py::test_double - assert 6 == 4",
        "caught: a test failed (tests of .)",
    ]


def test_mutant_gives_no_verdict_if_the_tests_fail_without_the_bug(
    doubling: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    write(doubling, "tests/test_double.py", "def test_double():\n    assert False\n")
    bug = ["--replace", "src/strom/__init__.py", "2 * x", "3 * x"]
    assert run_command(mutant, [*bug, "--", "-q"], doubling, monkeypatch) == 3
    shown = capsys.readouterr().out
    assert shown.startswith("--- stdout\n") and "--- stderr\n" in shown
    assert shown.endswith("the tests of . do not pass without the bug (exit code 1): no verdict\n")
    assert run_command(mutant, [*bug, "--tests-from", "HEAD", "--", "-q"], doubling, monkeypatch) == 0
    assert capsys.readouterr().out.endswith("caught: a test failed (tests of HEAD)\n")


def test_mutant_fails_for_a_bug_it_cannot_inject(doubling: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ToolError, match="OLD occurs 0 times"):
        run_command(mutant, ["--replace", "src/strom/__init__.py", "4 * x", "x", "--", "-q"], doubling, monkeypatch)


def test_run_examples_reports_the_examples_that_failed(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The examples are not run here (each needs an environment of its own): their outcomes are given."""
    for name in ("good", "bad", "slow"):
        write(repository, f"examples/{name}.py")
    outcomes = {
        "good.py": example_scripts.Passed(),
        "bad.py": example_scripts.Failed(1, "", "FAILED scores: expected 40, got 38\n"),
    }
    locked: list[str] = []
    monkeypatch.setattr(example_scripts, "run", lambda example: outcomes[example.name])
    monkeypatch.setattr(
        example_scripts, "check_types", lambda repository, example: example_scripts.TypeErrors(("ty",), "--- ty\n")
    )
    monkeypatch.setattr(example_scripts, "lock", lambda example: locked.append(example.name))
    assert run_command(run_examples, ["good"], repository, monkeypatch) == 0
    assert capsys.readouterr().out.startswith("good.py: ok (0.0 s)")
    assert run_command(run_examples, ["bad", "good"], repository, monkeypatch) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "bad.py: exit code 1 (0.0 s)",
        "--- stdout",
        "--- stderr",
        "FAILED scores: expected 40, got 38",
        "good.py: ok (0.0 s)",
    ]
    assert captured.err == "failed: bad.py\n"
    assert run_command(run_examples, ["--type", "good"], repository, monkeypatch) == 1
    assert capsys.readouterr().out.splitlines() == [
        "good.py: type errors (ty) (0.0 s)",
        "--- stdout",
        "--- ty",
        "--- stderr",
    ]
    assert run_command(run_examples, ["--lock"], repository, monkeypatch) == 0
    assert locked == ["bad.py", "good.py", "slow.py"]
    with pytest.raises(ToolError, match="unknown examples: nope.py"):
        run_command(run_examples, ["nope"], repository, monkeypatch)


def test_ab_measures_both_sides_in_interleaved_runs_and_prints_the_table(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No benchmark runs here (a real comparison takes minutes): the library copies and the measurements are
    given, a run of side B twice as slow as one of A."""
    commit_id = (write(repository, "a.txt"), commit(repository))[1]
    copies: list[tuple[Revision, str]] = []
    measured: list[tuple[str, str, tuple[str, ...]]] = []

    def library_copy(repository: Repository, revision: Revision, dest: Path) -> Path:
        copies.append((revision, dest.name))
        return dest

    def measure(
        repository: Repository, src: Path, out: Path, metric: str, pytest_args: Sequence[str]
    ) -> dict[str, float]:
        measured.append((src.name, metric, tuple(pytest_args)))
        return {"io: run": 2.0 if src.name == "B" else 1.0}

    monkeypatch.setattr(benchmark_comparison, "library_copy", library_copy)
    monkeypatch.setattr(benchmark_comparison, "measure", measure)
    monkeypatch.setattr(command_line, "require_modules", lambda *names: None)
    monkeypatch.setattr(ab, "_CPUINFO", repository.root / "no-cpuinfo")
    arguments = [commit_id, ".", "-n", "2", "--metric", "min", "--", "-k", "run"]
    assert run_command(ab, arguments, repository, monkeypatch) == 0
    assert copies == [(Commit(commit_id), "A"), (WorkingTree(), "B")]
    assert measured == [(side, "min", ("-k", "run")) for side in "ABBA"]
    captured = capsys.readouterr()
    assert [line.split()[:4] for line in captured.err.splitlines()] == [
        ["run", "1/2", "A", "done:"],
        ["run", "1/2", "B", "done:"],
        ["run", "2/2", "B", "done:"],
        ["run", "2/2", "A", "done:"],
    ]
    header, columns, row = captured.out.splitlines()
    assert header == f"A = {commit_id}, B = . (`.`: the working tree); min, median (IQR) of 2 runs each"
    assert columns.split() == ["benchmark", "A", "B", "B/A", "p"]
    assert row.split()[:2] == ["io:", "run"] and row.split()[-2] == "2.000"
    with pytest.raises(ToolError, match="no revision nowhere"):
        run_command(ab, ["nowhere"], repository, monkeypatch)


def test_ab_names_the_fast_cores_of_a_hybrid_cpu_when_unpinned(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    hybrid = "".join(f"processor : {cpu}\ncore id : {core}\n\n" for cpu, core in enumerate([0, 0, 4, 4, 8, 9]))
    monkeypatch.setattr(ab, "_CPUINFO", write(repository, "cpuinfo", hybrid))
    monkeypatch.setattr(command_line, "require_modules", lambda *names: None)
    monkeypatch.setattr(benchmark_comparison, "library_copy", lambda repository, revision, dest: dest)
    monkeypatch.setattr(benchmark_comparison, "measure", lambda *arguments: {"io: run": 1.0})
    monkeypatch.setattr(os, "sched_setaffinity", lambda pid, cpus: None)  # not this test's process
    commit(repository)
    for arguments, warned in ((["-n", "1"], True), (["-n", "1", "--cpus", "0"], False)):
        assert run_command(ab, arguments, repository, monkeypatch) == 0
        first = capsys.readouterr().err.splitlines()[0]
        assert (first == "cores of two speeds, unpinned: timings depend on the core; pin with --cpus 0-3") == warned


def test_ab_compares_the_library_of_two_revisions_for_real(
    repository: Repository, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """pytest-benchmark runs here, once per side; skipped where it is not installed (the tox envs of a Python
    version). The metric is a constant of each revision's library: 1.0 in HEAD, 3.0 in the working tree."""
    pytest.importorskip("pytest_benchmark")
    with_benchmark(repository)
    monkeypatch.setattr(ab, "_CPUINFO", repository.root / "no-cpuinfo")
    assert run_command(ab, ["HEAD", ".", "-n", "1", "--", *QUICK_BENCHMARK], repository, monkeypatch) == 0
    captured = capsys.readouterr()
    assert [line.split()[2] for line in captured.err.splitlines()] == ["A", "B"]
    assert captured.out.splitlines()[-1].split() == [
        "cost:",
        "test_cost",
        "1",
        "(",
        "0)",
        "3",
        "(",
        "0)",
        "3.000",
        "0.317",
    ]
