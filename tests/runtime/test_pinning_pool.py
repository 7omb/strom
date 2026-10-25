"""Tests of `strom._runtime.pinning_pool`: on which thread a call runs (any, or the one it is pinned to), in which
order a thread takes its calls, and what the shutdown does with those still queued.

The workers run their calls in their own thread and log to the test; calls are held by events, never by sleeps."""

import gc
import threading
import time
import weakref
from collections.abc import Callable, Generator
from concurrent.futures import Future
from contextlib import contextmanager
from typing import override

import pytest
from helpers import WAIT_LIMIT_TIME

from strom._runtime.backends import WorkerId
from strom._runtime.pinning_pool import PinningPool, Worker


class Workers:
    """Creates the workers of a pool and keeps what a test asks of them: which thread has which id, which
    workers hold what pinned calls need (`holding`), which were closed, and whose close fails (`failing`)."""

    def __init__(self) -> None:
        self.ids: dict[int, WorkerId] = {}  # by thread
        self.holding: set[WorkerId] = set()
        self.failing: set[WorkerId] = set()
        self.closed: list[WorkerId] = []

    def __call__(self, worker_id: WorkerId) -> Worker:
        self.ids[threading.get_ident()] = worker_id
        return _Direct(worker_id, self)


class CloseFailed(Exception):
    pass


class _Direct(Worker):
    def __init__(self, worker_id: WorkerId, workers: Workers) -> None:
        self._id = worker_id
        self._workers = workers

    @override
    def call[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        return fn(arg)

    @override
    def holds_pinned(self) -> bool:
        return self._id in self._workers.holding

    @override
    def close(self) -> None:
        self._workers.closed.append(self._id)
        if self._id in self._workers.failing:
            raise CloseFailed(self._id.token)


class Gate:
    """A call that says when it runs and then waits to be let go; it gives the thread it ran on."""

    def __init__(self) -> None:
        self.running = threading.Event()
        self.may_end = threading.Event()

    def __call__(self, log: list[str] | None) -> int:
        self.running.set()
        assert self.may_end.wait(WAIT_LIMIT_TIME)
        return threading.get_ident()


def thread_of(_: None) -> int:
    return threading.get_ident()


@contextmanager
def pool_of(workers: int, made: Workers) -> Generator[PinningPool]:
    pool = PinningPool(workers, "test", made)
    try:
        yield pool
    finally:
        try:
            pool.shutdown()
        except CloseFailed, BaseExceptionGroup:
            pass  # a test of failing closes has seen them


def held(pool: PinningPool) -> tuple[Gate, Future[int]]:
    """A call that runs on some thread until its gate lets it go."""
    gate = Gate()
    future = pool.submit(gate, None)
    assert gate.running.wait(WAIT_LIMIT_TIME)
    return gate, future


def wait_until_idle(pool: PinningPool, num: int) -> None:
    """Returns once `num` threads of the pool wait for a call: a thread goes idle a moment after the result of
    its call is out, and until then a call without affinity would not find it. Polls every half millisecond
    (intentional: the pool has no signal for it)."""
    deadline = time.monotonic() + WAIT_LIMIT_TIME
    while len(pool._idle_free) + len(pool._idle_holding) != num:
        assert time.monotonic() < deadline, "the threads did not go idle"
        time.sleep(0.0005)


def test_threads_start_on_demand_and_an_idle_one_is_taken_before_a_new_one() -> None:
    made = Workers()
    with pool_of(3, made) as pool:
        first = pool.submit(thread_of, None).result(WAIT_LIMIT_TIME)
        wait_until_idle(pool, 1)
        assert pool.submit(thread_of, None).result(WAIT_LIMIT_TIME) == first  # no second thread
        assert len(made.ids) == 1
        gates = [held(pool) for _ in range(3)]  # three calls at once: three threads
        assert len(made.ids) == 3
        waiting = pool.submit(thread_of, None)  # no fourth thread: it waits for one of the three
        assert not waiting.done()
        for gate, _ in gates:
            gate.may_end.set()
        assert waiting.result(WAIT_LIMIT_TIME) in made.ids
        assert len(made.ids) == 3
        assert sorted(thread.name for thread in threading.enumerate() if thread.name.startswith("test_")) == [
            "test_0",
            "test_1",
            "test_2",
        ]


def test_a_thread_takes_its_pinned_and_the_shared_calls_in_the_order_they_arrived() -> None:
    """Neither kind starves the other: a thread with calls pinned to it still takes the shared ones in turn."""
    made = Workers()
    ran: list[str] = []
    with pool_of(1, made) as pool:
        gate, running = held(pool)  # the one thread is busy
        worker = made.ids[next(iter(made.ids))]
        futures = [
            pool.submit(ran.append, "pinned 0", worker),
            pool.submit(ran.append, "shared 1"),
            pool.submit(ran.append, "pinned 2", worker),
            pool.submit(ran.append, "pinned 3", worker),
            pool.submit(ran.append, "shared 4"),
        ]
        gate.may_end.set()
        for future in futures:
            future.result(WAIT_LIMIT_TIME)
        assert ran == ["pinned 0", "shared 1", "pinned 2", "pinned 3", "shared 4"]
        assert pool.submit(thread_of, None, worker).result(WAIT_LIMIT_TIME) == running.result(WAIT_LIMIT_TIME)


class Kept:
    """An argument and result whose lifetime a test follows."""


def test_an_idle_thread_keeps_nothing_of_its_last_call() -> None:
    """Neither its argument nor its result (nor its function): a thread may wait long for its next call."""
    with pool_of(1, Workers()) as pool:
        argument = Kept()
        kept = weakref.ref(argument)
        future = pool.submit(lambda item: item, argument)
        assert future.result(WAIT_LIMIT_TIME) is argument
        wait_until_idle(pool, 1)
        del future, argument
        gc.collect()  # the free-threaded build may defer the release
        assert kept() is None


def test_a_pinned_call_goes_to_its_thread_also_when_others_are_idle() -> None:
    made = Workers()
    with pool_of(3, made) as pool:
        gates = [held(pool) for _ in range(3)]
        for gate, _ in gates:
            gate.may_end.set()
        threads = [future.result(WAIT_LIMIT_TIME) for _, future in gates]
        for thread in threads * 3:  # every thread is idle: affinity alone decides
            assert pool.submit(thread_of, None, made.ids[thread]).result(WAIT_LIMIT_TIME) == thread


def test_a_worker_the_pool_does_not_have_is_a_lookup_error() -> None:
    with pool_of(1, Workers()) as pool:
        with pytest.raises(LookupError, match="no worker gone"):
            pool.submit(thread_of, None, WorkerId("gone"))


def test_a_call_without_affinity_avoids_an_idle_thread_whose_worker_holds_what_pinned_calls_need() -> None:
    made = Workers()
    with pool_of(2, made) as pool:
        (gate_a, future_a), (gate_b, future_b) = held(pool), held(pool)
        gate_a.may_end.set()
        holder = future_a.result(WAIT_LIMIT_TIME)
        made.holding.add(made.ids[holder])  # as an open iterator would: taken when its thread next goes idle
        assert pool.submit(thread_of, None, made.ids[holder]).result(WAIT_LIMIT_TIME) == holder
        gate_b.may_end.set()
        free = future_b.result(WAIT_LIMIT_TIME)
        for _ in range(5):  # both idle: only the free one takes calls without affinity
            wait_until_idle(pool, 2)
            assert pool.submit(thread_of, None).result(WAIT_LIMIT_TIME) == free
        wait_until_idle(pool, 2)
        gate, busy = held(pool)  # the free one is busy: now the holder takes one rather than let it wait
        assert pool.submit(thread_of, None).result(WAIT_LIMIT_TIME) == holder
        gate.may_end.set()
        assert busy.result(WAIT_LIMIT_TIME) == free


def test_a_cleanup_runs_on_every_started_thread_behind_its_running_call() -> None:
    made = Workers()
    ran: list[tuple[str, int]] = []

    def log(what: str) -> None:
        ran.append((what, threading.get_ident()))

    with pool_of(3, made) as pool:  # two of three threads started
        gates = [held(pool), held(pool)]
        cleanups = pool.submit_cleanup(log, "cleanup")
        shared = pool.submit(log, "shared")  # a third thread takes it: the cleanup is not for that one
        shared.result(WAIT_LIMIT_TIME)
        assert len(cleanups) == 2 and not any(cleanup.done() for cleanup in cleanups)
        for gate, _ in gates:
            gate.may_end.set()
        for cleanup in cleanups:
            cleanup.result(WAIT_LIMIT_TIME)
        threads = {future.result(WAIT_LIMIT_TIME) for _, future in gates}
        assert {thread for what, thread in ran if what == "cleanup"} == threads
        assert [thread for what, thread in ran if what == "shared"][0] not in threads


def test_the_shutdown_cancels_queued_calls_runs_queued_cleanups_and_closes_the_workers() -> None:
    made = Workers()
    ran: list[str] = []
    pool = PinningPool(1, "test", made)
    gate, running = held(pool)
    worker = made.ids[next(iter(made.ids))]
    shared, pinned = pool.submit(ran.append, "shared"), pool.submit(ran.append, "pinned", worker)
    (cleanup,) = pool.submit_cleanup(ran.append, "cleanup")
    abandoned = pool.submit_cleanup(ran.append, "cleanup nobody waits for")[0]
    assert abandoned.cancel()  # a caller that stopped waiting: the cleanup runs all the same
    shutdown = threading.Thread(target=pool.shutdown)
    shutdown.start()
    while not (shared.cancelled() and pinned.cancelled()):  # the shutdown has begun; it waits for the running call
        assert shutdown.is_alive()
    assert made.closed == [] and ran == []
    gate.may_end.set()
    shutdown.join(WAIT_LIMIT_TIME)
    assert not shutdown.is_alive()
    assert running.result(0) in made.ids
    assert ran == ["cleanup", "cleanup nobody waits for"] and cleanup.done()
    assert made.closed == [worker]
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit(thread_of, None)
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit_cleanup(ran.append, "late")


def test_the_shutdown_wakes_idle_threads_and_raises_the_errors_of_the_closes() -> None:
    made = Workers()
    pool = PinningPool(3, "test", made)
    gates = [held(pool) for _ in range(3)]
    for gate, _ in gates:
        gate.may_end.set()
    threads = [future.result(WAIT_LIMIT_TIME) for _, future in gates]
    made.failing.update(made.ids[thread] for thread in threads[:2])
    wait_until_idle(pool, 3)
    with pytest.raises(BaseExceptionGroup) as info:  # every thread is woken, closes its worker and ends
        pool.shutdown()
    assert sorted(str(error) for error in info.value.exceptions) == sorted(worker.token for worker in made.failing)
    assert sorted(made.closed, key=str) == sorted(made.ids.values(), key=str)
    assert not [thread for thread in threading.enumerate() if thread.ident in threads]
