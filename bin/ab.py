"""Compares the benchmarks of two revisions of the library in interleaved runs (skill `validate-change`).

Run:  python bin/ab.py [A [B]] [-n RUNS] [--metric METRIC] [-- PYTEST_ARGS]

  A, B         revisions (e.g. HEAD, main~2); `.` is the working tree, uncommitted changes included, `:index`
               the staged changes (a snapshot to compare later edits with, no commit needed)
               (default: A = HEAD, B = .)
  -n RUNS      processes per revision (default: 9)
  --metric     a key of a benchmark's `extra_info` (default: us_per_input) or of its `stats` (min, median, ...)
  PYTEST_ARGS  passed on to pytest, e.g. `-k "event_loop"`, `--benchmark-min-rounds=5`

Both revisions run the working tree's `benchmarks/benchmark.py` (the same measurement; a benchmark using API
that a revision lacks fails there), each with its own copy of `src/` first on PYTHONPATH; `BENCH_SCALE` and
other variables pass through. The runs alternate in the order A B B A A B ..., so that a drift of the
machine (heat, other load) hits both alike. Each run is one process, measuring every selected benchmark; the
table shows per benchmark the median of the runs and their spread (IQR), the ratio B/A of the medians and p,
the two-sided p-value of a Mann-Whitney U test (normal approximation, no tie correction): below 0.05 the
runs of A and B differ beyond what their spread explains. Timings are meaningful only on a quiet machine;
repeat a surprising result.
"""

import argparse
import json
import statistics
import sys
import tempfile
from pathlib import Path
from typing import TypedDict

from _tools import ROOT, WORKING_TREE, library_copy, python_path_env, require_modules, run_detached, split_passthrough

TIMEOUT = 3600.0  # seconds per run


class _Benchmark(TypedDict):
    """The used part of a benchmark in pytest-benchmark's JSON."""

    name: str
    group: str | None
    stats: dict[str, float]
    extra_info: dict[str, float]


def measure(src: Path, out: Path, metric: str, pytest_args: list[str]) -> dict[str, float]:
    """One run of the benchmarks with the library in `src`: `metric` per benchmark (`group: name`)."""
    returncode, stdout, stderr = run_detached(
        [
            sys.executable,
            "-m",
            "pytest",
            "benchmarks/benchmark.py",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--benchmark-json={out}",
            *pytest_args,
        ],
        cwd=ROOT,
        timeout=TIMEOUT,
        env=python_path_env(src),
    )
    if returncode != 0:
        sys.exit(f"benchmark run failed ({returncode=}):\n{stdout}{stderr}")
    benchmarks: list[_Benchmark] = json.loads(out.read_text())["benchmarks"]
    if not benchmarks:
        sys.exit("no benchmark selected")
    values: dict[str, float] = {}
    for each in benchmarks:
        value = each["extra_info"].get(metric, each["stats"].get(metric))
        if value is None:
            sys.exit(f"benchmark {each['name']} has no metric {metric!r}")
        values[f"{each['group']}: {each['name']}"] = value
    return values


def mann_whitney_p(a: list[float], b: list[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test, normal approximation without tie correction."""
    u = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in a for y in b)
    mean = len(a) * len(b) / 2
    sd = (len(a) * len(b) * (len(a) + len(b) + 1) / 12) ** 0.5
    if sd == 0:
        return 1.0
    return 2 * (1 - statistics.NormalDist().cdf(abs(u - mean) / sd))


def spread(values: list[float]) -> float:
    """Interquartile range (0 for a single value)."""
    if len(values) < 2:
        return 0.0
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q3 - q1


def main() -> int:
    own, pytest_args = split_passthrough(sys.argv[1:])
    parser = argparse.ArgumentParser(description="Compares the benchmarks of two revisions in interleaved runs.")
    parser.add_argument("a", nargs="?", default="HEAD", help="revision A (default: HEAD)")
    parser.add_argument("b", nargs="?", default=WORKING_TREE, help="revision B (default: ., the working tree)")
    parser.add_argument("-n", "--runs", type=int, default=9, help="processes per revision (default: 9)")
    parser.add_argument("--metric", default="us_per_input", help="default: us_per_input")
    args = parser.parse_args(own)
    if args.runs < 1:
        parser.error("RUNS must be >= 1")
    require_modules("pytest", "pytest_benchmark")
    with tempfile.TemporaryDirectory(prefix="strom-ab-") as tmp:
        srcs = {side: library_copy(revision, Path(tmp) / side) for side, revision in (("A", args.a), ("B", args.b))}
        results: dict[str, dict[str, list[float]]] = {"A": {}, "B": {}}
        for run in range(args.runs):
            for side in ("A", "B") if run % 2 == 0 else ("B", "A"):
                values = measure(srcs[side], Path(tmp) / f"{side}{run}.json", args.metric, pytest_args)
                for name, value in values.items():
                    results[side].setdefault(name, []).append(value)
                print(f"run {run + 1}/{args.runs} {side} done", file=sys.stderr, flush=True)
    print(f"A = {args.a}, B = {args.b} (`.`: the working tree); {args.metric}, median (IQR) of {args.runs} runs each")
    width = max(map(len, results["A"]))
    print(f"{'benchmark':<{width}}  {'A':>18}  {'B':>18}  {'B/A':>6}  {'p':>6}")
    for name, a in results["A"].items():
        b = results["B"][name]  # the same benchmark file: the same benchmarks
        median_a, median_b = statistics.median(a), statistics.median(b)
        ratio = f"{median_b / median_a:6.3f}" if median_a else "     -"
        print(
            f"{name:<{width}}  {median_a:10.4g} ({spread(a):5.2g})  {median_b:10.4g} ({spread(b):5.2g})  "
            f"{ratio}  {mann_whitney_p(a, b):6.3f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
