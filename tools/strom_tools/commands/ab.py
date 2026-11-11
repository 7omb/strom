"""Compares the benchmarks of two revisions of the library in interleaved runs (skill `validate-change`).

Run:  python bin/ab.py [A [B]] [-n RUNS] [--metric METRIC] [--cpus CPUS] [-- PYTEST_ARGS]

  A, B         revisions (e.g. HEAD, main~2); `.` is the working tree, uncommitted changes included, `:index`
               the staged changes (a snapshot to compare later edits with, no commit needed)
               (default: A = HEAD, B = .)
  -n RUNS      processes per revision (default: 9)
  --metric     a key of a benchmark's `extra_info` (default: us_per_input) or of its `stats` (min, median, ...)
  --cpus       the CPUs all runs are pinned to, as taskset takes them (`0-11`, `0,2,4-7`; default: no pinning)
  PYTEST_ARGS  passed on to pytest, e.g. `-k "event_loop"`, `--benchmark-min-rounds=5`

Both revisions run the working tree's `benchmarks/benchmark.py` (the same measurement; a benchmark using API
that a revision lacks fails there), each with its own copy of `src/` first on PYTHONPATH; `BENCH_SCALE` and
other variables pass through. The runs alternate in the order A B B A A B ..., so that a drift of the
machine (heat, other load) hits both alike. Each run is one process, measuring every selected benchmark; after
each one, stderr says how many benchmarks it measured and how long the remaining runs take at this pace
(stop a comparison that takes too long and select fewer). The table shows per benchmark the median of the runs
and their spread (IQR), the ratio B/A of the medians and p, the two-sided p-value of a Mann-Whitney U test
(normal approximation, no tie correction): below 0.05 the runs of A and B differ beyond what their spread
explains. Timings are meaningful only on a quiet machine, and on a CPU with cores of two speeds only when
pinned to the cores of one (`--cpus`); repeat a surprising result.
"""

import os
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path

from strom_tools.change_checks.benchmark_comparison import Side, compared, cpu_set, interleaved, measure, table
from strom_tools.change_checks.revisions import WORKING_TREE, Revision, library_copy, parse
from strom_tools.commands import command_line
from strom_tools.workspace.repository import this_repository


def main(argv: Sequence[str]) -> int:
    own, pytest_args = command_line.split_passthrough(argv)
    parser = command_line.parser(__doc__)
    parser.add_argument("a", nargs="?", default="HEAD", help="revision A (default: HEAD)")
    parser.add_argument("b", nargs="?", default=WORKING_TREE, help="revision B (default: ., the working tree)")
    parser.add_argument("-n", "--runs", type=int, default=9, help="processes per revision (default: 9)")
    parser.add_argument("--metric", default="us_per_input", help="default: us_per_input")
    parser.add_argument("--cpus", help="the CPUs to pin all runs to, e.g. 0-11 (default: no pinning)")
    args = parser.parse_args(own)
    name_a: str = args.a
    name_b: str = args.b
    runs: int = args.runs
    metric: str = args.metric
    cpus: str | None = args.cpus
    if runs < 1:
        parser.error("RUNS must be >= 1")
    if cpus is not None:
        try:
            os.sched_setaffinity(0, cpu_set(cpus))  # the runs inherit it
        except (ValueError, OSError) as error:
            parser.error(f"--cpus {cpus}: {error}")
    command_line.require_modules("pytest", "pytest_benchmark")
    repository = this_repository()
    revisions: dict[Side, Revision] = {"A": parse(repository, name_a), "B": parse(repository, name_b)}
    results: dict[Side, dict[str, list[float]]] = {"A": {}, "B": {}}
    with tempfile.TemporaryDirectory(prefix="strom-ab-") as tmp:
        srcs = {side: library_copy(repository, revision, Path(tmp) / side) for side, revision in revisions.items()}
        started_at, num_done = time.monotonic(), 0
        for run, side in interleaved(runs):
            values = measure(repository, srcs[side], Path(tmp) / f"{side}{run}.json", metric, pytest_args)
            for name, value in values.items():
                results[side].setdefault(name, []).append(value)
            num_done += 1
            left_time = (time.monotonic() - started_at) / num_done * (2 * runs - num_done)
            print(
                f"run {run + 1}/{runs} {side} done: {len(values)} benchmarks, "
                f"about {left_time / 60:.1f} min for the remaining runs",
                file=sys.stderr,
                flush=True,
            )
    pinned = f", on the CPUs {cpus}" if cpus is not None else ""
    print(f"A = {name_a}, B = {name_b} (`.`: the working tree); {metric}, median (IQR) of {runs} runs each{pinned}")
    print(table(compared(results["A"], results["B"])))
    return 0
