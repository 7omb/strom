from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from tool_helpers import QUICK_BENCHMARK, with_benchmark

from strom_tools.change_checks.benchmark_comparison import (
    Row,
    _Benchmark,
    _mann_whitney_p,
    _metric_values,
    _spread,
    compared,
    cpu_set,
    interleaved,
    measure,
    table,
)
from strom_tools.change_checks.revisions import Commit, WorkingTree, library_copy
from strom_tools.tool_error import ToolError
from strom_tools.workspace.repository import Repository

samples = st.lists(st.floats(min_value=0, max_value=100), min_size=1, max_size=12)


def test_a_run_measures_the_working_trees_benchmarks_with_a_copy_of_the_library(
    repository: Repository, tmp_path: Path
) -> None:
    """pytest-benchmark runs here; skipped where it is not installed (the tox envs of a Python version)."""
    pytest.importorskip("pytest_benchmark")
    with_benchmark(repository)
    committed = library_copy(repository, Commit("HEAD"), tmp_path / "A")
    working = library_copy(repository, WorkingTree(), tmp_path / "B")
    assert measure(repository, committed, tmp_path / "a.json", "us_per_input", QUICK_BENCHMARK) == {
        "cost: test_cost": 1.0
    }
    assert measure(repository, working, tmp_path / "b.json", "us_per_input", QUICK_BENCHMARK) == {
        "cost: test_cost": 3.0
    }
    assert measure(repository, working, tmp_path / "c.json", "min", QUICK_BENCHMARK)["cost: test_cost"] > 0
    with pytest.raises(ToolError, match=r"benchmark run failed \(returncode=5\)"):
        measure(repository, working, tmp_path / "d.json", "min", [*QUICK_BENCHMARK, "-k", "no_such_benchmark"])


@given(samples, samples)
def test_p_is_a_probability_and_symmetric(a: list[float], b: list[float]) -> None:
    p = _mann_whitney_p(a, b)
    assert 0 <= p <= 1
    assert p == pytest.approx(_mann_whitney_p(b, a))


@given(samples)
def test_a_sample_does_not_differ_from_itself(a: list[float]) -> None:
    assert _mann_whitney_p(a, a) == pytest.approx(1.0)


def test_separated_samples_differ_and_overlapping_ones_do_not() -> None:
    low, high = [1.0, 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8], [2.0, 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8]
    assert _mann_whitney_p(low, high) < 0.001
    assert _mann_whitney_p([1.0, 2.0, 3.0, 4.0], [1.5, 2.5, 3.5, 0.5]) > 0.5


def test_spread_is_the_interquartile_range() -> None:
    assert _spread([5.0]) == 0.0
    assert _spread([1.0, 2.0, 3.0, 4.0, 5.0]) == 2.0


def test_cpu_set_reads_what_taskset_takes() -> None:
    assert cpu_set("0-3") == {0, 1, 2, 3}
    assert cpu_set("0,2,4-6") == {0, 2, 4, 5, 6}
    with pytest.raises(ValueError, match="invalid literal"):
        cpu_set("fast")


def test_runs_are_interleaved_a_b_b_a() -> None:
    assert list(interleaved(3)) == [(0, "A"), (0, "B"), (1, "B"), (1, "A"), (2, "A"), (2, "B")]


def benchmark(stats: dict[str, float], extra_info: dict[str, float]) -> _Benchmark:
    return {"name": "run", "group": "io", "stats": stats, "extra_info": extra_info}


def test_a_metric_is_read_from_extra_info_or_the_stats() -> None:
    stats = {"min": 2.0, "us_per_input": 9.0}
    assert _metric_values([benchmark(stats, {})], "min") == {"io: run": 2.0}
    assert _metric_values([benchmark(stats, {"us_per_input": 3.0})], "us_per_input") == {"io: run": 3.0}
    with pytest.raises(ToolError, match="benchmark run has no metric 'median'"):
        _metric_values([benchmark(stats, {})], "median")
    with pytest.raises(ToolError, match="no benchmark selected"):
        _metric_values([], "min")


def test_the_table_compares_the_medians_of_both_sides() -> None:
    rows = compared(
        {"io: run": [1.0, 2.0, 3.0], "cpu: idle": [0.0, 0.0]}, {"io: run": [4.0, 4.0, 5.0], "cpu: idle": [1.0, 1.0]}
    )
    assert rows[0] == Row("io: run", 2.0, 1.0, 4.0, 0.5, _mann_whitney_p([1.0, 2.0, 3.0], [4.0, 4.0, 5.0]))
    lines = table(rows).splitlines()
    assert lines[0].split() == ["benchmark", "A", "B", "B/A", "p"]
    assert lines[1].split() == ["io:", "run", "2", "(", "1)", "4", "(", "0.5)", "2.000", f"{rows[0].p:.3f}"]
    assert lines[2].split()[-2] == "-", "no ratio to a median of zero"
    assert len({len(line) for line in lines}) == 1
