"""The benchmarks of two revisions of the library in interleaved runs, and the statistics of their comparison.

Both sides run the working tree's `benchmarks/benchmark.py`, each with its own copy of the library first on
PYTHONPATH. Usage and how to read the table: `strom_tools.commands.ab`."""

import json
import math
import statistics
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypedDict

from strom_tools.change_checks.revisions import Revision, library_copy, python_path_env
from strom_tools.tool_error import ToolError
from strom_tools.workspace.processes import output, pytest_command, run_process
from strom_tools.workspace.repository import Repository

_TIMEOUT = 3600.0  # seconds per run

type Side = Literal["A", "B"]


class _Benchmark(TypedDict):
    """The used part of a benchmark in pytest-benchmark's JSON."""

    name: str
    group: str | None
    stats: dict[str, float]
    extra_info: dict[str, float]


class _Report(TypedDict):
    benchmarks: list[_Benchmark]


def measure(repository: Repository, src: Path, out: Path, metric: str, pytest_args: Sequence[str]) -> dict[str, float]:
    """One run of the benchmarks with the library in `src`: `metric` per benchmark (`group: name`), in the order
    they are defined (not pytest-randomly's), the same in every run."""
    run = run_process(
        pytest_command("benchmarks/benchmark.py", "-q", "-p", "no:randomly", f"--benchmark-json={out}", *pytest_args),
        cwd=repository.root,
        timeout=_TIMEOUT,
        env=python_path_env(src),
    )
    if run.returncode != 0:
        cause = (
            "; the library of this revision lacks a module the benchmarks import (they are the working tree's):"
            " take a revision that has it"
            if "ModuleNotFoundError: No module named 'strom." in output(run)
            else ""
        )
        raise ToolError(f"benchmark run failed (returncode={run.returncode}){cause}:\n{output(run)}")
    report: _Report = json.loads(out.read_text())
    return _metric_values(report["benchmarks"], metric)


def _metric_values(benchmarks: Sequence[_Benchmark], metric: str) -> dict[str, float]:
    """`metric` of each benchmark of a report (a key of its `extra_info` or of its `stats`), by `group: name`."""
    if not benchmarks:
        raise ToolError("no benchmark selected")
    values: dict[str, float] = {}
    for each in benchmarks:
        value = each["extra_info"].get(metric, each["stats"].get(metric))
        if value is None:
            raise ToolError(f"benchmark {each['name']} has no metric {metric!r}")
        values[f"{each['group']}: {each['name']}"] = value
    return values


def _interleaved(runs: int) -> Iterator[tuple[int, Side]]:
    """The run number (from 0) and the side of each process, in the order A B B A A B ...: a drift of the machine
    (heat, other load) hits both sides alike."""
    for run in range(runs):
        sides: tuple[Side, Side] = ("A", "B") if run % 2 == 0 else ("B", "A")
        yield run, sides[0]
        yield run, sides[1]


def _mann_whitney_p(a: Sequence[float], b: Sequence[float]) -> float:
    """Two-sided p-value of the Mann-Whitney U test, normal approximation without tie correction."""
    u = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x in a for y in b)
    mean = len(a) * len(b) / 2
    sd = math.sqrt(len(a) * len(b) * (len(a) + len(b) + 1) / 12)
    if sd == 0:
        return 1.0
    return 2 * (1 - statistics.NormalDist().cdf(abs(u - mean) / sd))


def _spread(values: Sequence[float]) -> float:
    """Interquartile range (0 for a single value)."""
    if len(values) < 2:
        return 0.0
    q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    return q3 - q1


def cpu_set(cpus: str) -> set[int]:
    """The CPUs of a list such as `0-11` or `0,2,4-7` (`ValueError` for anything else)."""
    numbers: set[int] = set()
    for part in cpus.split(","):
        first, _, last = part.partition("-")
        numbers.update(range(int(first), int(last or first) + 1))
    return numbers


def cpu_list(cpus: set[int]) -> str:
    """The CPUs as `cpu_set` reads them, runs of consecutive ones as ranges (`0-3,6`)."""
    parts: list[str] = []
    for cpu in sorted(cpus):
        if parts and cpu - 1 in cpus:
            first = parts.pop().split("-")[0]
            parts.append(f"{first}-{cpu}")
        else:
            parts.append(str(cpu))
    return ",".join(parts)


def fast_cpus(cpuinfo: str) -> set[int] | None:
    """The CPUs of the fast cores, if `cpuinfo` (`/proc/cpuinfo`) shows cores of two speeds: on a hybrid CPU only
    the fast ones have two threads each, so a CPU whose core has a sibling is fast where some cores have none
    (2026-11-11, an i7-12700H). None where it can't tell: one kind of core, or none with two threads."""
    cores: dict[tuple[str, str], list[int]] = {}
    for block in cpuinfo.split("\n\n"):
        parts = (line.partition(":") for line in block.splitlines())
        fields = {key.strip(): value.strip() for key, _, value in parts}
        if "processor" in fields and "core id" in fields:
            cores.setdefault((fields.get("physical id", ""), fields["core id"]), []).append(int(fields["processor"]))
    fast = {cpu for cpus in cores.values() if len(cpus) > 1 for cpu in cpus}
    single = any(len(cpus) == 1 for cpus in cores.values())
    return fast if fast and single else None


@dataclass(frozen=True)
class Row:
    """One benchmark, compared."""

    name: str
    median_a: float
    spread_a: float
    median_b: float
    spread_b: float
    p: float


def _compared(a: Mapping[str, Sequence[float]], b: Mapping[str, Sequence[float]]) -> list[Row]:
    """A row per benchmark of side A, from the values of its runs on both sides (the same benchmark file: the
    same benchmarks)."""
    return [
        Row(
            name,
            statistics.median(values),
            _spread(values),
            statistics.median(b[name]),
            _spread(b[name]),
            _mann_whitney_p(values, b[name]),
        )
        for name, values in a.items()
    ]


@dataclass(frozen=True)
class RunDone:
    """A run of the benchmarks ended."""

    run: int
    """From 0; a run is one process per side."""
    side: Side
    num_benchmarks: int
    """Measured in it."""
    left_time: float
    """Seconds the remaining runs take at the pace so far."""


@dataclass(frozen=True)
class Compared:
    """Every run ended: the comparison."""

    rows: list[Row]


def comparison(
    repository: Repository,
    revisions: Mapping[Side, Revision],
    num_runs: int,
    metric: str,
    pytest_args: Sequence[str],
) -> Iterator[RunDone | Compared]:
    """Measures `metric` with the library of each side's revision in `num_runs` interleaved runs per side (each
    with its own copy of the library, in a temporary directory); yields each run as it ends, then the rows."""
    values: dict[Side, dict[str, list[float]]] = {"A": {}, "B": {}}
    with tempfile.TemporaryDirectory(prefix="strom-ab-") as tmp:
        srcs = {side: library_copy(repository, revision, Path(tmp) / side) for side, revision in revisions.items()}
        started_at = time.monotonic()
        for num_done, (run, side) in enumerate(_interleaved(num_runs), start=1):
            measured = measure(repository, srcs[side], Path(tmp) / f"{side}{run}.json", metric, pytest_args)
            for name, value in measured.items():
                values[side].setdefault(name, []).append(value)
            left_time = (time.monotonic() - started_at) / num_done * (2 * num_runs - num_done)
            yield RunDone(run, side, len(measured), left_time)
    yield Compared(_compared(values["A"], values["B"]))


def table(rows: Sequence[Row]) -> str:
    """The rows under a header: per side the median and the spread, the ratio B/A of the medians and p."""
    width = max(len(row.name) for row in rows)
    lines = [f"{'benchmark':<{width}}  {'A':>18}  {'B':>18}  {'B/A':>6}  {'p':>6}"]
    for row in rows:
        ratio = f"{row.median_b / row.median_a:6.3f}" if row.median_a else "     -"
        lines.append(
            f"{row.name:<{width}}  {row.median_a:10.4g} ({row.spread_a:5.2g})  "
            f"{row.median_b:10.4g} ({row.spread_b:5.2g})  {ratio}  {row.p:6.3f}"
        )
    return "\n".join(lines)
