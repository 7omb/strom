"""Tests of `strom._interpreters.offloaders`: skipping pool tasks after a failure, releasing what a run left
in the workers (its scope), and measuring pool tasks (the layer `_Measured`, on its own and in runs)."""

import asyncio
import itertools
import sqlite3
import threading
from collections.abc import Callable, Iterator
from typing import override

import pytest
from helpers import (
    WAIT_LIMIT_TIME,
    CountingThreads,
    Failure,
    Pickling,
    RecorderFailure,
    at_most_three_lazily,
    collect_pickling,
    double,
    fail_on_7,
    inc,
    outputs_of,
    pid_of,
    raising_on,
    run_error,
    stats_of,
)

import strom as P
from strom._interpreters.offloaders import FailureFlag, PoolCalls, PoolTaskSkipped, _Measured, _OnBackends
from strom._runtime.backends import WorkerId
from strom._runtime.pools import backends_of
from strom.backends import StreamingBackend
from strom.metrics import Event, PoolTaskFinished, Recorder, StatsRecorder, StepId

RAN: list[str] = []  # what `ran` ran: the workers of the backends here are threads of this process


def ran(name: str) -> str:
    RAN.append(name)
    return name


def guard_backends(name: str) -> Callable[[], StreamingBackend]:
    """A backend config whose workers share the run's memory ("threads") or get everything pickled."""
    return P.Threads(workers=1) if name == "threads" else Pickling(workers=1)


@pytest.mark.parametrize("name", ["threads", "pickling"])
async def test_a_pool_task_of_a_failed_run_is_skipped_in_its_worker(name: str) -> None:
    """The guard travels with the function, so every backend skips: a thread sees the run's flag itself, a
    worker without shared memory the copy pickled with the task."""
    RAN.clear()
    failed = FailureFlag()
    config = guard_backends(name)
    async with P.Pools.open_on(cpu=config, io=config) as pools:
        calls = _OnBackends(backends_of(pools), failed)
        assert await calls.cpu(ran, "before") == "before"
        failed.set()
        with pytest.raises(PoolTaskSkipped):
            await calls.cpu(ran, "skipped")
        with pytest.raises(PoolTaskSkipped):
            await calls.io(ran, "skipped", None)
    assert RAN == ["before"]


@pytest.mark.parametrize(("name", "shares_memory"), [("threads", True), ("pickling", False)])
async def test_a_failing_pool_task_sets_the_flag_where_its_worker_shares_the_runs_memory(
    name: str, shares_memory: bool
) -> None:
    """In the worker, before the event loop learns of the error: the next queued task of a thread is skipped.
    A worker without shared memory sets its copy; the run's flag is set by its failing step."""
    failed = FailureFlag()
    config = guard_backends(name)
    async with P.Pools.open_on(cpu=config, io=config) as pools:
        calls = _OnBackends(backends_of(pools), failed)
        with pytest.raises(Failure):
            await calls.cpu(fail_on_7, 7)
    assert failed.is_set() is shares_memory


async def test_internal_skip_signal_never_replaces_the_users_error() -> None:
    # Minimal example found by Hypothesis: a skipped task's signal used to cancel the real error.
    stage = P.io_stage(fail_on_7, concurrency=4) | P.io_stage(double, buffer_size=1)
    async with P.Pools.open(cpu_workers=1, io_workers=8, cpu_backend="thread") as pools:
        for _ in range(100):
            with run_error(Failure):
                await outputs_of(stage, [0, 7, 0], pools)


@pytest.mark.parametrize("recorded", [False, True], ids=["no recorder", "StatsRecorder"])
async def test_skipped_tasks_do_not_end_a_stream_early(recorded: bool) -> None:
    # A step task whose pool task was skipped used to return, ending its step's stream as if it were complete.
    # A join that is not on the failing path then reported incomplete inputs besides the user's error.
    pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
    join_a = pairs | P.product(P.io_stage(inc), P.identity()) | P.fst()
    join_b = pairs | P.product(P.io_stage(fail_on_7), P.identity()) | P.fst()  # error is slower
    stage = join_a | pairs | P.product(join_b, P.identity()) | P.fst()
    async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:  # pool tasks queue up
        for _ in range(30):
            recorder: Recorder | None = StatsRecorder() if recorded else None
            with run_error(Failure):
                await outputs_of(stage, range(6, 12), pools, recorder=recorder)


async def test_queued_pool_tasks_are_skipped_after_failure() -> None:
    io_pool = CountingThreads(workers=1)
    started: list[int] = []
    lock = threading.Lock()

    def first_fails(item: int) -> list[int]:
        """The first call fails once the pool tasks of all inputs are queued behind it in the one-thread pool."""
        with lock:
            started.append(item)
            is_first = len(started) == 1
        if is_first:
            assert io_pool.wait_until_submitted(8), "the other pool tasks were never queued"
            raise ValueError("first fails")
        return [item]

    async with P.Pools.open_on(cpu=P.Threads(workers=1), io=io_pool) as pools:
        with run_error(ValueError, "^first fails"):
            await outputs_of(P.io_stage(first_fails, concurrency=8), range(8), pools)
    assert len(started) == 1  # after `with`: every pool task has run or was skipped


class KeptRows:
    """A closable iterator that is not a generator: only an explicit `close()` closes it (reference
    counting cannot, the test keeps a reference). Its first item waits for `first_item_may_come`."""

    def __init__(self) -> None:
        self.first_item_may_come = threading.Event()
        self.closed = threading.Event()

    def __iter__(self) -> Iterator[int]:
        return self

    def __next__(self) -> int:
        assert self.first_item_may_come.wait(WAIT_LIMIT_TIME)
        return 1

    def close(self) -> None:
        self.closed.set()


async def test_an_iterator_opened_for_a_cancelled_handling_is_closed() -> None:
    # The run fails while a pool thread opens an io_stage's iterator; the iterator that pool task
    # returns after the step was cancelled is closed (was: left to reference counting).
    rows = KeptRows()
    opening = threading.Event()

    def open_rows(_: int) -> KeptRows:
        opening.set()
        return rows

    def fail_while_opening(_: int) -> list[int]:
        assert opening.wait(WAIT_LIMIT_TIME)
        raise ValueError("boom")

    pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
    stage = pairs | P.product(P.io_stage(open_rows), P.io_stage(fail_while_opening))
    async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:
        with run_error(ValueError, "^boom"):
            await outputs_of(stage, [1], pools)
        # a pool task behind the run's release on the free thread: a release that did not wait for the open
        # has run (too early) once it returns, rather than waiting in the queue for the pools' close
        assert await outputs_of(P.io_stage(inc), [1], pools) == [2]
        assert not rows.closed.is_set()
        rows.first_item_may_come.set()  # the pool task now returns the open iterator
    assert rows.closed.is_set()  # closing the pools waited for the pool task


async def test_an_iterator_whose_opening_cannot_be_recorded_is_closed() -> None:
    # The recorder fails on the pool task that opened the iterator: the step never receives it.
    rows = KeptRows()
    rows.first_item_may_come.set()

    def open_rows(_: int) -> KeptRows:
        return rows

    async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:
        with run_error(RecorderFailure):
            await outputs_of(P.io_stage(open_rows), [1], pools, recorder=raising_on(PoolTaskFinished, "open_rows"))
    assert rows.closed.is_set()  # closed in a pool thread; closing the pools waited for it


def test_an_iterator_whose_opening_cannot_be_recorded_is_closed_on_its_worker() -> None:
    # Without shared memory, the iterator stays in the registry of the worker that opened it: the release of
    # the run's scope must reach that worker. `collect_pickling` checks that no worker keeps an iterator.
    # (An iterator, not a list: a list comes whole and leaves nothing in the worker.)
    recorder = raising_on(PoolTaskFinished, "at_most_three_lazily")
    with run_error(RecorderFailure):
        collect_pickling(P.io_stage(at_most_three_lazily), [3], recorder=recorder)


def test_an_iterator_stopped_early_is_closed_on_its_worker() -> None:
    # Leaving the block after one output cancels the run while the endless iterator is open: the release must
    # reach the worker holding it (two workers take turns).
    io = Pickling(workers=2)

    async def first_output() -> int:
        async with P.Pools.open_on(cpu=P.Threads(workers=1), io=io) as pools:
            async with P.stream(P.io_stage(itertools.count, buffer_size=1), [5], pools) as outputs:
                async for out in outputs:
                    return out
        raise AssertionError("no output")

    assert asyncio.run(first_output()) == 5
    assert io.num_registered() == 0


def sqlite_rows(item: int) -> Iterator[int]:
    """Five rows of a connection opened for this input: sqlite3 binds a connection and its cursors to the thread
    that created them (`check_same_thread`), also for the close."""
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("CREATE TABLE numbers (value INTEGER)")
        connection.executemany("INSERT INTO numbers VALUES (?)", [(10 * item + value,) for value in range(5)])
        for (value,) in connection.execute("SELECT value FROM numbers ORDER BY value"):
            yield value
    finally:
        connection.close()


async def test_an_io_stage_iterates_thread_bound_objects_on_their_thread() -> None:
    """More iterators open at once than threads, each fetching its rows one pool task at a time."""
    async with P.Pools.open(cpu_workers=1, io_workers=3, cpu_backend="thread") as pools:
        outputs = await outputs_of(P.io_stage(sqlite_rows, concurrency=4), range(8), pools)
    assert sorted(outputs) == sorted(10 * item + value for item in range(8) for value in range(5))


class DirectCalls(PoolCalls):
    """Pool calls run directly in the caller's thread, logging each call's resource and affinity."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, WorkerId | None]] = []

    @override
    async def cpu[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        self.calls.append(("cpu", None))
        return fn(arg)

    @override
    async def io[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None) -> B:
        self.calls.append(("io", affinity))
        return fn(arg)


STEP_ID = StepId((), 1, "inc", 1)


async def test_the_measuring_layer_records_each_call_timed_in_the_worker() -> None:
    inner, events = DirectCalls(), list[Event]()
    measured = _Measured(inner, events.append, STEP_ID)
    worker = WorkerId("w")
    assert await measured.cpu(inc, 1) == [2]
    assert await measured.io(inc, 2, worker) == [3]
    assert inner.calls == [("cpu", None), ("io", worker)]  # the affinity passes through
    assert [type(event) for event in events] == [PoolTaskFinished, PoolTaskFinished]
    for event in events:
        assert isinstance(event, PoolTaskFinished)
        assert event.step_id == STEP_ID
        assert event.submitted_at <= event.ended_at
        assert 0 <= event.running_time <= event.ended_at - event.submitted_at


async def test_the_measuring_layer_raises_the_recorders_error() -> None:
    def failing(_: Event) -> None:
        raise RecorderFailure

    measured = _Measured(DirectCalls(), failing, STEP_ID)
    with pytest.raises(RecorderFailure):
        await measured.io(inc, 1, None)


def test_process_pool_times_are_measured_in_the_worker() -> None:
    _, stats = stats_of(P.cpu_stage(pid_of, concurrency=2), range(4), cpu_backend="process")
    (s,) = [s for s in stats.step_stats if s.step_id.name == "pid_of"]
    assert s.num_pool_tasks == 4
    assert s.pool_running_time >= 4 * 0.005 * 0.9  # pid_of sleeps 0.005 s in the worker
