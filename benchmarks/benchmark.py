"""Benchmarks for the `strom` package, including reference implementations without the pipeline.

Requires pytest-benchmark. Run:

    pytest benchmarks/benchmark.py               statistics per group of benchmarks that belong together
    BENCH_SCALE=0.2 pytest benchmarks/benchmark.py
                                                 fewer items, for a quick run
    pytest benchmarks/benchmark.py --benchmark-autosave
                                                 also save the run (in .benchmarks/)
    pytest benchmarks/benchmark.py --benchmark-compare --benchmark-compare-fail=min:10%
                                                 compare with the last saved run, fail on a regression
    pytest benchmarks/benchmark.py --benchmark-disable
                                                 run every benchmark once without timing: only checks results

The tables show the time of one run (all items). `extra_info` of every benchmark, part of the saved
data and of `--benchmark-json`, records the time per input and per output in microseconds (best
round): `us_per_input` and `us_per_output`. Inputs are the run's inputs, or for a stage on one input,
the items its first step makes (for references: the items processed), outputs the items the measured
stages emit (none for a stage ending in an effect). Do not use pytest-xdist: it disables the benchmarks.

The rounds of a benchmark run on one event loop that lasts for the benchmark (`make_runs`), with its
pools opened on it: no round pays for starting a loop. Every benchmark runs once untimed before it is
measured: pools create their workers lazily, so the first run would also measure starting them. With
--benchmark-disable this warm-up is skipped.

The cost of one step per input is (t_n - t_0) / n, from the row "identity only" (t_0) and a row with n
more steps (t_n) of the "event loop" group (same number of items); dividing t_n by n would charge the
inputs and the run itself to the steps. Each row starts with that identity. Fusion runs the "n
event-loop steps" with it as one group, so they give the cost of a member of a group; "n async_stage
steps" are not fused and give the cost of a step with its own task and queue. The other factories are
compared the same way: event-loop ones in the "event loop" group, pool ones in "pool factories", which
has its own "identity only" row (fewer items). For rows that are not 1:1 (a filter dropping items, an
effect) the difference also contains the outputs the consumer no longer takes, so it can be negative.

The fixed cost of a run (t_run) is the row "1 item, identity only" of "run overhead"; the cost per
input of a shape with n inputs is (t_n - t_run) / (n - 1), e.g. with "identity only" of "event loop".

Benchmarks whose work is waiting (sleeps) also record `overhead_us_per_input`: the best round minus
the ideal time (the waits, overlapped as far as concurrency and pool size allow), per input. It
includes how late `time.sleep` wakes up.

The "latency" group records, besides the run time, the time from the start of a run to its first
output and percentiles of each output's latency (from the run taking its input to the consumer
taking the output), over the measured runs. The latencies include the waits in queues: the run takes
inputs ahead as far as their queue allows. These benchmarks have a fixed number of inputs (not
scaled), as the latencies depend on it.

The tests only assert that results are complete; timings are not asserted, because they depend on
the machine (use --benchmark-compare-fail to check for regressions between two runs; it compares the
run times, not `extra_info`).

Naming follows tests/helpers.py.
"""

import asyncio
import os
import statistics
import time
from collections.abc import AsyncIterable, AsyncIterator, Callable, Coroutine, Generator, Iterable, Iterator
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from contextlib import AsyncExitStack, contextmanager
from functools import partial
from typing import NamedTuple, Protocol

import pytest

import strom as P
from strom.metrics import Recorder, StatsRecorder

pytestmark = pytest.mark.filterwarnings("ignore:cpu_backend='thread' with the GIL enabled")

SCALE = float(os.environ.get("BENCH_SCALE", "1"))


def scaled_num_items(num_base_items: int) -> int:
    return max(10, int(num_base_items * SCALE))


# ------------------------------------------------- work functions (module level: picklable)
def neg_value(item: int) -> int:  # for the references without the pipeline
    return -item


def inc_value(item: int) -> int:
    return item + 1


def neg(item: int) -> list[int]:  # stage functions emit the items of their result
    return [-item]


def inc(item: int) -> list[int]:
    return [item + 1]


def keep_in(received: list[int], item: int) -> list[int]:  # an effect only: emits nothing
    received.append(item)
    return []


def nothing(item: int) -> list[int]:  # an effect only, in a worker process
    return []


def keeps_all(item: int) -> bool:
    return True


def keeps_one_in_100(item: int) -> bool:
    return item % 100 == 0


async def async_neg(item: int) -> AsyncIterator[int]:
    yield -item


async def async_numbers(num_items: int, _: None) -> AsyncIterator[int]:
    for item in range(num_items):
        yield item


def repeat_as_list(item: int, times: int) -> list[list[int]]:
    return [[item] * times]  # ONE item: a list


def many(item: int) -> list[int]:
    return list(range(item))


def many_lazily(item: int) -> Iterator[int]:  # an iterator: an `io_stage` streams it, one pool task per item
    yield from range(item)


def many_as_list(item: int) -> list[list[int]]:
    return [list(range(item))]  # ONE item: a list


def sleep_1ms(item: int) -> list[int]:
    """Simulated IO: 1 ms of waiting without CPU."""
    time.sleep(0.001)
    return [item]


def sleep_2ms(item: int) -> list[int]:
    """Simulated IO: 2 ms of waiting without CPU."""
    time.sleep(0.002)
    return [item]


def sleep_10ms(item: int) -> list[int]:
    """Simulated IO: 10 ms of waiting without CPU."""
    time.sleep(0.01)
    return [item]


def hundred_slowly(pair: tuple[int, int]) -> Iterator[tuple[int, int]]:
    """1:100 with 0.2 ms of waiting before each output: a stage that streams emits the first early."""
    for i in range(100):
        time.sleep(0.0002)
        yield i, i


# ------------------------------------------------------------------------------- helpers
class _Stats(Protocol):
    min: float


class _Metadata(Protocol):
    stats: _Stats


class Benchmark(Protocol):
    """The part of pytest-benchmark's `benchmark` fixture that is used here (the plugin is not typed)."""

    extra_info: dict[str, float]
    stats: _Metadata | None  # None until the benchmark has run, and when benchmarks are disabled
    disabled: bool  # --benchmark-disable (or pytest-xdist): the function runs once, untimed

    def __call__[R](self, function_to_benchmark: Callable[[], R]) -> R: ...


def measure[R](
    benchmark: Benchmark,
    run: Callable[[], R],
    num_inputs: int,
    num_outputs: int | None = None,
    ideal_time: float | None = None,
) -> R:
    """Benchmarks `run` after one untimed warm-up run.

    Records the time per input and, if there are outputs, per output in `extra_info` (`num_outputs`:
    `num_inputs` unless given), and, given the `ideal_time` of a run (its waits), the overhead per
    input. Without timing (--benchmark-disable) `run` runs once, without the warm-up."""
    if num_outputs is None:
        num_outputs = num_inputs
    benchmark.extra_info["num_inputs"] = num_inputs
    benchmark.extra_info["num_outputs"] = num_outputs
    if not benchmark.disabled:
        run()  # warm-up: pool workers start lazily
    result = benchmark(run)
    if benchmark.stats is not None:
        best_time = benchmark.stats.stats.min
        benchmark.extra_info["us_per_input"] = best_time / num_inputs * 1e6
        if num_outputs > 0:
            benchmark.extra_info["us_per_output"] = best_time / num_outputs * 1e6
        if ideal_time is not None:
            benchmark.extra_info["overhead_us_per_input"] = (best_time - ideal_time) / num_inputs * 1e6
    return result


type Pair = tuple[int, int]
type NestedPair = tuple[tuple[int, int], int]


def pairs(num_items: int) -> list[Pair]:
    return [(i, i) for i in range(num_items)]  # built once, not in every measured run


def same_ints() -> P.Stage[int, int]:
    """The identity on ints: the first member of the rows compared with "identity only"."""
    return P.identity()


def numbers_up_to(num_items: int, _: None) -> range:  # top-level: picklable in a partial
    return range(num_items)


class PairCase(NamedTuple):
    """A stage on pairs and how to benchmark it. A typed table of cases makes the type checkers check
    each `make_stage` (lambdas in a `parametrize` list are inferred as `Any`)."""

    make_stage: Callable[[], P.Stage[Pair, Pair]]
    num_base_items: int
    io_workers: int
    outputs_per_input: int = 1
    ideal_time_per_input: float | None = None  # its waits, overlapped as concurrency allows (see `measure`)


async def outputs_of[I, O](
    stage: P.Stage[I, O], inputs: Iterable[I] | AsyncIterable[I], pools: P.Pools, recorder: Recorder | None = None
) -> list[O]:
    async with P.stream(stage, inputs, pools, recorder=recorder) as outputs:
        return [out async for out in outputs]


class Runs:
    """Runs on one event loop that lasts for a benchmark, with pools opened on it: no round starts a loop."""

    def __init__(self, runner: asyncio.Runner, pools: P.Pools) -> None:
        self.runner = runner
        self.pools = pools

    def outputs[I, O](
        self, stage: P.Stage[I, O], inputs: Iterable[I] | AsyncIterable[I], recorder: Recorder | None = None
    ) -> list[O]:
        """The outputs of a run, as a list."""
        return self.runner.run(outputs_of(stage, inputs, self.pools, recorder))

    def run[R](self, coroutine: Coroutine[object, object, R]) -> R:
        return self.runner.run(coroutine)


@contextmanager
def make_runs(cpu_workers: int = 1, io_workers: int = 5, cpu_backend: P.CpuBackendKind = "thread") -> Generator[Runs]:
    with asyncio.Runner() as runner:
        stack = AsyncExitStack()  # holds `Pools.open` open across the rounds' `runner.run` calls
        pools = runner.run(
            stack.enter_async_context(
                P.Pools.open(cpu_workers=cpu_workers, io_workers=io_workers, cpu_backend=cpu_backend)
            )
        )
        try:
            yield Runs(runner, pools)
        finally:
            runner.run(stack.aclose())


async def asyncio_offload_by_workers(
    executor: Executor, fn: Callable[[int], int], items: range, concurrency: int
) -> list[int]:
    """Reference: plain asyncio + run_in_executor, shaped like a step: `concurrency` tasks, each
    taking one item after another from a shared iterator."""
    loop, outputs = asyncio.get_running_loop(), []
    remaining: Iterator[int] = iter(items)

    async def worker() -> None:
        for item in remaining:  # shared: each item goes to one worker
            outputs.append(await loop.run_in_executor(executor, fn, item))

    async with asyncio.TaskGroup() as tg:
        for _ in range(concurrency):
            tg.create_task(worker())
    return outputs


# --------------------------------------------------------- orchestration (event loop) cost
@pytest.mark.benchmark(group="event loop")
def test_event_loop_reference_plain_loop(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(50_000)
    outputs = measure(benchmark, lambda: [neg_value(x) for x in range(num_items)], num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="event loop")
@pytest.mark.parametrize(
    "num_steps", [0, 1, 3, 6], ids=["identity only", "1 event-loop step", "3 event-loop steps", "6 event-loop steps"]
)
def test_event_loop_steps(benchmark: Benchmark, num_steps: int) -> None:
    num_items = scaled_num_items(50_000)
    stage = same_ints()
    for _ in range(num_steps):
        stage = stage | P.stage(neg)
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="event loop")
@pytest.mark.parametrize(
    "num_steps", [1, 3, 6], ids=["1 async_stage step", "3 async_stage steps", "6 async_stage steps"]
)
def test_event_loop_async_stage_steps(benchmark: Benchmark, num_steps: int) -> None:
    """Not fused: each step has its own tasks and output queue (compare with "identity only")."""
    num_items = scaled_num_items(50_000)
    stage = same_ints()
    for _ in range(num_steps):
        stage = stage | P.async_stage(async_neg)
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="event loop")
def test_event_loop_async_stage_on_one_input(benchmark: Benchmark) -> None:
    """The items of one async iterable, made for one input."""
    num_items = scaled_num_items(50_000)
    stage = P.async_stage(partial(async_numbers, num_items))
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, [None]), num_items)
    assert len(outputs) == num_items


FILTERS: dict[str, Callable[[int], bool]] = {
    "where keeps all": keeps_all,
    "where drops 99%": keeps_one_in_100,  # most inputs are SKIPs of the group: the fairness path
}


@pytest.mark.benchmark(group="event loop")
@pytest.mark.parametrize("pred", list(FILTERS.values()), ids=list(FILTERS))
def test_event_loop_filter(benchmark: Benchmark, pred: Callable[[int], bool]) -> None:
    num_items = scaled_num_items(50_000)
    num_kept = sum(1 for item in range(num_items) if pred(item))
    stage = same_ints() | P.where(pred)
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items, num_kept)
    assert len(outputs) == num_kept


@pytest.mark.benchmark(group="event loop")
def test_event_loop_effect_run(benchmark: Benchmark) -> None:
    """A run of a stage ending in an effect that emits nothing (compare with "identity only", whose
    consumer takes every item)."""
    num_items = scaled_num_items(50_000)

    def run_once(runs: Runs) -> int:
        received: list[int] = []
        runs.outputs(same_ints() | P.stage(partial(keep_in, received)), range(num_items))
        return len(received)

    with make_runs() as runs:
        num_received = measure(benchmark, lambda: run_once(runs), num_items, 0)
    assert num_received == num_items


# ------------------------------------------------------------------------ pool factories
@pytest.mark.benchmark(group="pool factories")
def test_pool_factories_identity_only(benchmark: Benchmark) -> None:
    """Reference of this group (fewer items than "event loop": pool factories cost more per input)."""
    num_items = scaled_num_items(5_000)
    stage = same_ints()
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="pool factories")
def test_pool_factories_io_stage_on_one_input(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(5_000)
    stage = P.io_stage(partial(numbers_up_to, num_items))  # one pool task per item
    with make_runs(io_workers=1) as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, [None]), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="pool factories")
def test_pool_factories_cpu_stage_on_one_input(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(5_000)
    stage = P.cpu_stage(partial(numbers_up_to, num_items))  # ONE pool task in a worker process; picklable
    with make_runs(cpu_backend="process") as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, [None]), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="pool factories")
def test_pool_factories_io_effect(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(5_000)

    def run_once(runs: Runs) -> int:
        received: list[int] = []  # appended to by pool threads (list.append is thread-safe)
        runs.outputs(same_ints() | P.io_stage(partial(keep_in, received), concurrency=4), range(num_items))
        return len(received)

    with make_runs(io_workers=4) as runs:
        num_received = measure(benchmark, lambda: run_once(runs), num_items, 0)
    assert num_received == num_items


@pytest.mark.benchmark(group="pool factories")
def test_pool_factories_cpu_effect(benchmark: Benchmark) -> None:
    """Only checks that the run completes: a worker process cannot report back what it received."""
    num_items = scaled_num_items(5_000)
    stage = same_ints() | P.cpu_stage(nothing, concurrency=4)
    with make_runs(cpu_workers=1, cpu_backend="process") as runs:
        measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items, 0)


# -------------------------------------------------------------------------- thread pool
@pytest.mark.benchmark(group="thread pool")
def test_thread_pool_reference_executor_map(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(20_000)
    with ThreadPoolExecutor(5) as executor:
        outputs = measure(benchmark, lambda: list(executor.map(inc_value, range(num_items))), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="thread pool")
def test_thread_pool_reference_asyncio_offload_by_workers(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(20_000)
    with ThreadPoolExecutor(5) as executor, asyncio.Runner() as runner:  # one loop, as `make_runs`
        outputs = measure(
            benchmark,
            lambda: runner.run(asyncio_offload_by_workers(executor, inc_value, range(num_items), 5)),
            num_items,
        )
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="thread pool")
@pytest.mark.parametrize("concurrency", [1, 5])
def test_thread_pool_io_stage(benchmark: Benchmark, concurrency: int) -> None:
    num_items = scaled_num_items(20_000)
    with make_runs(io_workers=5) as runs:
        stage = P.io_stage(inc, concurrency=concurrency)
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


# ------------------------------------------------------------------------- process pool
@pytest.mark.benchmark(group="process pool")
@pytest.mark.parametrize("chunksize", [1, 100])
def test_process_pool_reference_executor_map(benchmark: Benchmark, chunksize: int) -> None:
    num_items = scaled_num_items(5_000)
    with ProcessPoolExecutor(1) as executor:
        outputs = measure(
            benchmark, lambda: list(executor.map(inc_value, range(num_items), chunksize=chunksize)), num_items
        )
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="process pool")
def test_process_pool_reference_asyncio_offload_by_workers(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(5_000)
    with ProcessPoolExecutor(1) as executor, asyncio.Runner() as runner:  # one loop, as `make_runs`
        outputs = measure(
            benchmark,
            lambda: runner.run(asyncio_offload_by_workers(executor, inc_value, range(num_items), 4)),
            num_items,
        )
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="process pool")
@pytest.mark.parametrize("concurrency", [1, 4])
def test_process_pool_cpu_stage(benchmark: Benchmark, concurrency: int) -> None:
    num_items = scaled_num_items(5_000)
    with make_runs(cpu_workers=1, io_workers=1, cpu_backend="process") as runs:
        stage = P.cpu_stage(inc, concurrency=concurrency)
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


# ----------------------------------------------------------- tuple combinators (lifting)
LIFTED_STAGES: dict[str, PairCase] = {
    "first(stage)": PairCase(lambda: P.first(P.stage(neg)), 20_000, io_workers=1),
    "second(stage | stage)": PairCase(lambda: P.second(P.stage(neg) | P.stage(neg)), 20_000, io_workers=1),
    "first(io | io), concurrency 4": PairCase(
        lambda: P.first(P.io_stage(inc, concurrency=4) | P.io_stage(inc, concurrency=4)), 5_000, io_workers=8
    ),
    "first(io | flatten | io), 1:3": PairCase(
        lambda: P.first(
            P.io_stage(partial(repeat_as_list, times=3), concurrency=4) | P.flatten() | P.io_stage(inc, concurrency=4)
        ),
        3_000,
        io_workers=8,
        outputs_per_input=3,
    ),
    "first(io, 2 ms work), concurrency 8": PairCase(
        lambda: P.first(P.io_stage(sleep_2ms, concurrency=8)), 800, io_workers=8, ideal_time_per_input=0.002 / 8
    ),
}


def measure_pairs(benchmark: Benchmark, case: PairCase) -> None:
    """Benchmarks a stage on pairs (i, i) and checks the number of outputs."""
    num_items = scaled_num_items(case.num_base_items)
    num_outputs = num_items * case.outputs_per_input
    stage, items = case.make_stage(), pairs(num_items)
    ideal_time = None if case.ideal_time_per_input is None else num_items * case.ideal_time_per_input
    with make_runs(io_workers=case.io_workers) as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, items), num_items, num_outputs, ideal_time)
    assert len(outputs) == num_outputs


@pytest.mark.benchmark(group="lifted stages")
@pytest.mark.parametrize("case", list(LIFTED_STAGES.values()), ids=list(LIFTED_STAGES))
def test_lifted_stages(benchmark: Benchmark, case: PairCase) -> None:
    measure_pairs(benchmark, case)


# ------------------------------------------------------------------------------ product
PRODUCT_STAGES: dict[str, PairCase] = {
    "product(stage, stage)": PairCase(lambda: P.product(P.stage(neg), P.stage(neg)), 20_000, io_workers=16),
    "product(io c=4, io c=4)": PairCase(
        lambda: P.product(P.io_stage(inc, concurrency=4), P.io_stage(inc, concurrency=4)), 5_000, io_workers=16
    ),
    "product(io | io c=4, stage)": PairCase(
        lambda: P.product(P.io_stage(inc, concurrency=4) | P.io_stage(inc, concurrency=4), P.stage(neg)),
        5_000,
        io_workers=16,
    ),
    "product(io 2 ms c=8, io 2 ms c=8)": PairCase(  # both branches at once: 16 pool threads for 2 x 8
        lambda: P.product(P.io_stage(sleep_2ms, concurrency=8), P.io_stage(sleep_2ms, concurrency=8)),
        800,
        io_workers=16,
        ideal_time_per_input=0.002 / 8,
    ),
}


@pytest.mark.benchmark(group="product stages")
@pytest.mark.parametrize("case", list(PRODUCT_STAGES.values()), ids=list(PRODUCT_STAGES))
def test_product_stages(benchmark: Benchmark, case: PairCase) -> None:
    measure_pairs(benchmark, case)


LIFTED_AND_NESTED_PRODUCT: dict[str, Callable[[], P.Stage[NestedPair, NestedPair]]] = {
    "first(product(stage, stage))": lambda: P.first(P.product(P.stage(neg), P.stage(neg))),
    "product(product(stage, stage), stage)": lambda: P.product(P.product(P.stage(neg), P.stage(neg)), P.stage(neg)),
}


@pytest.mark.benchmark(group="lifted and nested product")
@pytest.mark.parametrize("make_stage", list(LIFTED_AND_NESTED_PRODUCT.values()), ids=list(LIFTED_AND_NESTED_PRODUCT))
def test_lifted_and_nested_product(
    benchmark: Benchmark, make_stage: Callable[[], P.Stage[NestedPair, NestedPair]]
) -> None:
    num_items = scaled_num_items(20_000)
    items = [((i, i), i) for i in range(num_items)]  # built once, not in every measured run
    stage = make_stage()
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, items), num_items)
    assert len(outputs) == num_items


@pytest.mark.benchmark(group="streaming")
def test_streaming_fan_out(benchmark: Benchmark) -> None:
    num_items = scaled_num_items(100_000)
    freeze_times: list[float] = []  # the largest gap of the event loop's heartbeat, per run

    async def run_with_heartbeat(pools: P.Pools) -> int:
        largest_gap_time, done = 0.0, False

        async def heartbeat() -> None:
            """Wakes every millisecond; the largest gap between wake-ups is the longest freeze."""
            nonlocal largest_gap_time
            last_beat_at = time.perf_counter()
            while not done:
                await asyncio.sleep(0.001)
                beat_at = time.perf_counter()
                largest_gap_time, last_beat_at = max(largest_gap_time, beat_at - last_beat_at), beat_at

        heartbeat_task = asyncio.create_task(heartbeat())
        stage = P.io_stage(many_as_list) | P.flatten() | P.stage(neg)
        outputs = await outputs_of(stage, [num_items], pools)
        done = True
        await heartbeat_task
        freeze_times.append(largest_gap_time)
        return len(outputs)

    with make_runs(io_workers=4) as runs:  # ONE input: the io_stage emits num_items
        num_items_out = measure(benchmark, lambda: runs.run(run_with_heartbeat(runs.pools)), 1, num_items)
    measured_freeze_times = freeze_times if benchmark.disabled else freeze_times[1:]  # without the warm-up run
    benchmark.extra_info["max_loop_freeze_ms"] = max(measured_freeze_times) * 1e3
    assert num_items_out == num_items


IO_ONE_TO_MANY: dict[str, Callable[[], P.Stage[int, int]]] = {
    "io_stage | flatten (collects first)": lambda: P.io_stage(many_as_list) | P.flatten(),
    "io_stage of an iterator (one pool task per item)": lambda: P.io_stage(many_lazily),
    "io_stage of a list (one pool task)": lambda: P.io_stage(many),
}


@pytest.mark.benchmark(group="io 1:0..n")
@pytest.mark.parametrize("make_stage", list(IO_ONE_TO_MANY.values()), ids=list(IO_ONE_TO_MANY))
def test_io_one_to_many(benchmark: Benchmark, make_stage: Callable[[], P.Stage[int, int]]) -> None:
    num_items = scaled_num_items(20_000)
    with make_runs(io_workers=4) as runs:  # ONE input: the stage emits num_items
        stage = make_stage()
        outputs = measure(benchmark, lambda: runs.outputs(stage, [num_items]), 1, num_items)
    assert sorted(outputs) == list(range(num_items))


# ------------------------------------------------- event-loop steps around a pool step
@pytest.mark.benchmark(group="event-loop steps around a pool step")
@pytest.mark.parametrize("num_event_loop_steps", [0, 4], ids=["io_stage only", "2 event-loop steps before, 2 after"])
def test_event_loop_steps_around_a_pool_step(benchmark: Benchmark, num_event_loop_steps: int) -> None:
    num_items = scaled_num_items(10_000)
    stage: P.Stage[int, int] = P.io_stage(inc, concurrency=4)
    for _ in range(num_event_loop_steps // 2):
        stage = P.stage(neg) | stage | P.stage(neg)
    with make_runs(io_workers=4) as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items)
    assert len(outputs) == num_items


# ------------------------------------------------------------------ cost of recording
class RecordingCase(NamedTuple):
    run: Callable[[int, Runs, Recorder | None], list[object]]  # of the number of inputs
    num_base_items: int


def run_six_event_loop_steps(num_items: int, runs: Runs, recorder: Recorder | None) -> list[object]:
    stage = same_ints() | P.stage(neg) | P.stage(neg) | P.stage(neg) | P.stage(neg) | P.stage(neg) | P.stage(neg)
    return [*runs.outputs(stage, range(num_items), recorder=recorder)]


def run_product(num_items: int, runs: Runs, recorder: Recorder | None) -> list[object]:
    stage = P.product(P.stage(neg), P.stage(neg))
    return [*runs.outputs(stage, pairs(num_items), recorder=recorder)]


def run_io_stage(num_items: int, runs: Runs, recorder: Recorder | None) -> list[object]:
    return [*runs.outputs(P.io_stage(inc, concurrency=5), range(num_items), recorder=recorder)]


def run_cpu_stage(num_items: int, runs: Runs, recorder: Recorder | None) -> list[object]:
    return [*runs.outputs(P.cpu_stage(inc), range(num_items), recorder=recorder)]


RECORDING: dict[str, RecordingCase] = {
    "one group of 6 event-loop steps": RecordingCase(run_six_event_loop_steps, 20_000),
    "product(stage, stage)": RecordingCase(run_product, 20_000),  # recorded: branch steps through counted focuses
    "io_stage": RecordingCase(run_io_stage, 10_000),  # recorded: every pool task timed (the measuring layer)
    "cpu_stage (thread backend)": RecordingCase(run_cpu_stage, 10_000),
}


@pytest.mark.parametrize("recorded", [False, True], ids=["no recorder", "StatsRecorder"])
@pytest.mark.parametrize(
    "case",
    [
        pytest.param(case, id=name, marks=pytest.mark.benchmark(group=f"recording: {name}"))
        for name, case in RECORDING.items()
    ],
)
def test_recording(benchmark: Benchmark, case: RecordingCase, recorded: bool) -> None:
    num_items = scaled_num_items(case.num_base_items)

    def make_recorder() -> Recorder | None:
        return StatsRecorder() if recorded else None

    with make_runs() as runs:
        outputs = measure(benchmark, lambda: case.run(num_items, runs, make_recorder()), num_items)
    assert len(outputs) == num_items


# ---------------------------------------------------------- concurrency vs. pool size
@pytest.mark.benchmark(group="concurrency vs pool size")
@pytest.mark.parametrize("concurrency", [1, 5])
def test_concurrency_vs_pool_size(benchmark: Benchmark, concurrency: int) -> None:
    num_items, io_workers = scaled_num_items(100), 5
    ideal_time = num_items * 0.01 / min(concurrency, io_workers)  # 10 ms of IO per item
    with make_runs(io_workers=io_workers) as runs:
        stage = P.io_stage(sleep_10ms, concurrency=concurrency)
        outputs = measure(benchmark, lambda: runs.outputs(stage, range(num_items)), num_items, ideal_time=ideal_time)
    assert len(outputs) == num_items


# ----------------------------------------------------------------------------- latency
def stamped_pairs(num_inputs: int) -> Iterator[tuple[Pair, float]]:
    for i in range(num_inputs):
        yield (i, i), time.perf_counter()  # stamped when the run takes it (lazily, on the event loop)


class LatencyCase(NamedTuple):
    """A stage on pairs, applied with `first`, so that the emission time passes through it."""

    make_stage: Callable[[], P.Stage[Pair, Pair]]
    num_inputs: int  # fixed, not scaled: the latencies depend on it
    outputs_per_input: int = 1


class LatencyRun(NamedTuple):
    first_output_time: float  # from the start of the run to its first output
    latency_times: list[float]  # per output: from the run taking its input to its arrival


def buffered_before_slower(buffer_size: int) -> P.Stage[Pair, Pair]:
    """A step of 1 ms whose output queue (`buffer_size`) fills in front of a step of 2 ms."""
    return P.first(P.io_stage(sleep_1ms, buffer_size=buffer_size) | P.io_stage(sleep_2ms))


def one_branch_after_the_other() -> P.Stage[Pair, Pair]:
    """first(io 2 ms) | second(io 2 ms): the meaning of `product`, without running both at once."""
    first_io: P.Stage[Pair, Pair] = P.first(P.io_stage(sleep_2ms))  # annotated: mypy infers Never for X
    return first_io | P.second(P.io_stage(sleep_2ms))


LATENCY: dict[str, LatencyCase] = {
    "io_stage 1:100 (streams)": LatencyCase(lambda: P.io_stage(hundred_slowly), 4, outputs_per_input=100),
    "cpu_stage 1:100 (collects first), thread backend": LatencyCase(  # threads: no pickling, only collecting
        lambda: P.cpu_stage(hundred_slowly), 4, outputs_per_input=100
    ),
    "product(io 2 ms, io 2 ms)": LatencyCase(lambda: P.product(P.io_stage(sleep_2ms), P.io_stage(sleep_2ms)), 40),
    "first(io 2 ms) | second(io 2 ms)": LatencyCase(one_branch_after_the_other, 40),
    **{
        f"first(io 1 ms, buffer_size {buffer_size} | io 2 ms)": LatencyCase(
            partial(buffered_before_slower, buffer_size), 40
        )
        for buffer_size in [1, 10, 100]
    },
}


@pytest.mark.benchmark(group="latency")
@pytest.mark.parametrize("case", list(LATENCY.values()), ids=list(LATENCY))
def test_latency(benchmark: Benchmark, case: LatencyCase) -> None:
    num_outputs = case.num_inputs * case.outputs_per_input
    stage: P.Stage[tuple[Pair, float], tuple[Pair, float]] = P.first(case.make_stage())
    latency_runs: list[LatencyRun] = []

    async def run_once(pools: P.Pools) -> int:
        arrivals: list[tuple[float, float]] = []  # (emitted_at, arrived_at) per output, taken by the consumer
        started_at = time.perf_counter()
        async with P.stream(stage, stamped_pairs(case.num_inputs), pools) as outputs:
            async for out in outputs:
                arrivals.append((out[1], time.perf_counter()))
        latency_runs.append(
            LatencyRun(arrivals[0][1] - started_at, [arrived_at - emitted_at for emitted_at, arrived_at in arrivals])
        )
        return len(arrivals)

    with make_runs(io_workers=4) as runs:
        num_arrived = measure(benchmark, lambda: runs.run(run_once(runs.pools)), case.num_inputs, num_outputs)
    measured_runs = latency_runs if benchmark.disabled else latency_runs[1:]  # without the warm-up run
    latency_times = [latency_time for run in measured_runs for latency_time in run.latency_times]
    benchmark.extra_info["first_output_ms"] = statistics.median(run.first_output_time for run in measured_runs) * 1e3
    benchmark.extra_info["latency_p50_ms"] = statistics.median(latency_times) * 1e3
    benchmark.extra_info["latency_p99_ms"] = statistics.quantiles(latency_times, n=100)[98] * 1e3
    assert num_arrived == num_outputs


# ------------------------------------------------------------------------- run overhead
@pytest.mark.benchmark(group="run overhead")
@pytest.mark.parametrize("num_steps", [1, 10], ids=["1 item, identity only", "1 item, 10 event-loop steps"])
def test_run_overhead_one_item(benchmark: Benchmark, num_steps: int) -> None:
    """The fixed cost of a run with existing `Pools`: setting it up, including fusion."""
    stage = same_ints()
    for _ in range(num_steps - 1):
        stage = stage | P.stage(neg)
    with make_runs() as runs:
        outputs = measure(benchmark, lambda: runs.outputs(stage, [0]), 1)
    assert len(outputs) == 1


CPU_BACKENDS: list[P.CpuBackendKind] = ["thread", "process"]


@pytest.mark.benchmark(group="run overhead")
@pytest.mark.parametrize("cpu_backend", CPU_BACKENDS)
def test_run_overhead_new_pools(benchmark: Benchmark, cpu_backend: P.CpuBackendKind) -> None:
    """Opening `Pools`, its first pool task (a pool worker starts) and closing it, for a 1-item run, on one
    event loop.

    The warm-up run pays the process backend's start of the forkserver (once per interpreter)."""
    stage = P.cpu_stage(inc)

    async def run_with_new_pools() -> list[int]:
        async with P.Pools.open(cpu_workers=1, io_workers=5, cpu_backend=cpu_backend) as pools:
            return await outputs_of(stage, [0], pools)

    with asyncio.Runner() as runner:
        outputs = measure(benchmark, lambda: runner.run(run_with_new_pools()), 1)
    assert outputs == [1]
