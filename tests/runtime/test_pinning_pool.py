"""Tests of `strom._runtime.pinning_pool`: on which thread a call runs (any, or the one it is pinned to), in which
order a thread takes its calls, what the shutdown does with those still queued, what the caller of an awaited
call gets (`PinningPool.run`), and what becomes of a call or a result nobody waits for.

The workers run their calls in their own thread and log to the test; calls are held by events, never by sleeps."""

import asyncio
import contextlib
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
from strom._runtime.pinning_pool import PinningPool, Worker, _Caller


class Workers:
    """Creates the workers of a pool and keeps what a test asks of them: which thread has which id, which
    workers hold what pinned calls need (`stateful`), which were closed, and whose close fails (`failing`)."""

    def __init__(self) -> None:
        self.ids: dict[int, WorkerId] = {}  # by thread
        self.stateful: set[WorkerId] = set()
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
    def holds_state(self) -> bool:
        return self._id in self._workers.stateful

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


class OnFuture[B](_Caller[B]):
    """A caller that waits on a `concurrent.futures.Future`, from the test's own thread; a dropped call's future
    is cancelled."""

    def __init__(self) -> None:
        self.future: Future[B] = Future()

    @override
    def waits(self) -> bool:
        return self.future.set_running_or_notify_cancel()

    @override
    def set_result(self, result: B) -> None:
        self.future.set_result(result)

    @override
    def set_exception(self, error: BaseException) -> None:
        self.future.set_exception(error)

    @override
    def drop(self) -> None:
        self.future.cancel()


def submitted[A, B](pool: PinningPool, fn: Callable[[A], B], arg: A, affinity: WorkerId | None = None) -> Future[B]:
    """`pool.run` with the result or error on a future (cancelling it while the call waits: the call never runs)."""
    caller = OnFuture[B]()
    pool._submit(fn, arg, caller, affinity)
    return caller.future


@contextmanager
def pool_of(workers: int, made: Workers) -> Generator[PinningPool]:
    pool = PinningPool(workers, "test", made)
    try:
        yield pool
    finally:
        with contextlib.suppress(CloseFailed, BaseExceptionGroup):  # a test of failing closes has seen them
            pool.shutdown()


def held(pool: PinningPool) -> tuple[Gate, Future[int]]:
    """A call that runs on some thread until its gate lets it go."""
    gate = Gate()
    future = submitted(pool, gate, None)
    assert gate.running.wait(WAIT_LIMIT_TIME)
    return gate, future


def wait_until_idle(pool: PinningPool, num: int) -> None:
    """Returns once `num` threads of the pool wait for a call: a thread goes idle a moment after the result of
    its call is out, and until then an unpinned call would not find it. Polls every half millisecond
    (intentional: the pool has no signal for it)."""
    deadline = time.monotonic() + WAIT_LIMIT_TIME
    while len(pool._idle_stateless) + len(pool._idle_stateful) != num:
        assert time.monotonic() < deadline, "the threads did not go idle"
        time.sleep(0.0005)


def test_threads_start_on_demand_and_an_idle_one_is_taken_before_a_new_one() -> None:
    made = Workers()
    with pool_of(3, made) as pool:
        first = submitted(pool, thread_of, None).result(WAIT_LIMIT_TIME)
        wait_until_idle(pool, 1)
        assert submitted(pool, thread_of, None).result(WAIT_LIMIT_TIME) == first  # no second thread
        assert len(made.ids) == 1
        gates = [held(pool) for _ in range(3)]  # three calls at once: three threads
        assert len(made.ids) == 3
        waiting = submitted(pool, thread_of, None)  # no fourth thread: it waits for one of the three
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


def test_a_thread_takes_its_pinned_and_the_unpinned_calls_in_the_order_they_arrived() -> None:
    """Neither kind starves the other: a thread with calls pinned to it still takes the unpinned ones in turn."""
    made = Workers()
    ran: list[str] = []
    with pool_of(1, made) as pool:
        gate, running = held(pool)  # the one thread is busy
        worker_id = made.ids[next(iter(made.ids))]
        futures = [
            submitted(pool, ran.append, "pinned 0", worker_id),
            submitted(pool, ran.append, "unpinned 1"),
            submitted(pool, ran.append, "pinned 2", worker_id),
            submitted(pool, ran.append, "pinned 3", worker_id),
            submitted(pool, ran.append, "unpinned 4"),
        ]
        gate.may_end.set()
        for future in futures:
            future.result(WAIT_LIMIT_TIME)
        assert ran == ["pinned 0", "unpinned 1", "pinned 2", "pinned 3", "unpinned 4"]
        assert submitted(pool, thread_of, None, worker_id).result(WAIT_LIMIT_TIME) == running.result(WAIT_LIMIT_TIME)


class Kept:
    """An argument and result whose lifetime a test follows."""


def test_an_idle_thread_keeps_nothing_of_its_last_call() -> None:
    """Neither its argument nor its result (nor its function): a thread may wait long for its next call."""
    with pool_of(1, Workers()) as pool:
        argument = Kept()
        kept = weakref.ref(argument)
        future = submitted(pool, lambda item: item, argument)
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
            assert submitted(pool, thread_of, None, made.ids[thread]).result(WAIT_LIMIT_TIME) == thread


def test_a_worker_the_pool_does_not_have_is_a_lookup_error() -> None:
    with pool_of(1, Workers()) as pool, pytest.raises(LookupError, match="no worker gone"):
        submitted(pool, thread_of, None, WorkerId("gone"))


def test_an_unpinned_call_avoids_an_idle_thread_whose_worker_holds_what_pinned_calls_need() -> None:
    made = Workers()
    with pool_of(2, made) as pool:
        (gate_a, future_a), (gate_b, future_b) = held(pool), held(pool)
        gate_a.may_end.set()
        holder = future_a.result(WAIT_LIMIT_TIME)
        made.stateful.add(made.ids[holder])  # as an open iterator would: taken when its thread next goes idle
        assert submitted(pool, thread_of, None, made.ids[holder]).result(WAIT_LIMIT_TIME) == holder
        gate_b.may_end.set()
        stateless = future_b.result(WAIT_LIMIT_TIME)
        for _ in range(5):  # both idle: only the stateless one takes unpinned calls
            wait_until_idle(pool, 2)
            # the holder goes idle last: the thread an unpinned call would take first, were it stateless too
            assert submitted(pool, thread_of, None, made.ids[holder]).result(WAIT_LIMIT_TIME) == holder
            wait_until_idle(pool, 2)
            assert submitted(pool, thread_of, None).result(WAIT_LIMIT_TIME) == stateless
        wait_until_idle(pool, 2)
        gate, busy = held(pool)  # the stateless one is busy: now the holder takes one rather than let it wait
        assert submitted(pool, thread_of, None).result(WAIT_LIMIT_TIME) == holder
        gate.may_end.set()
        assert busy.result(WAIT_LIMIT_TIME) == stateless


def test_a_cleanup_runs_on_every_started_thread_behind_its_running_call() -> None:
    made = Workers()
    ran: list[tuple[str, int]] = []

    def log(what: str) -> None:
        ran.append((what, threading.get_ident()))

    with pool_of(3, made) as pool:  # two of three threads started
        gates = [held(pool), held(pool)]
        cleanups = pool.submit_cleanup(log, "cleanup")
        unpinned = submitted(pool, log, "unpinned")  # a third thread takes it: the cleanup is not for that one
        unpinned.result(WAIT_LIMIT_TIME)
        assert len(cleanups) == 2 and not any(cleanup.done() for cleanup in cleanups)
        for gate, _ in gates:
            gate.may_end.set()
        for cleanup in cleanups:
            cleanup.result(WAIT_LIMIT_TIME)
        threads = {future.result(WAIT_LIMIT_TIME) for _, future in gates}
        assert {thread for what, thread in ran if what == "cleanup"} == threads
        assert next(thread for what, thread in ran if what == "unpinned") not in threads


def test_the_shutdown_drops_queued_calls_runs_queued_cleanups_and_closes_the_workers() -> None:
    made = Workers()
    ran: list[str] = []
    pool = PinningPool(1, "test", made)
    gate, running = held(pool)
    worker_id = made.ids[next(iter(made.ids))]
    unpinned, pinned = submitted(pool, ran.append, "unpinned"), submitted(pool, ran.append, "pinned", worker_id)
    (cleanup,) = pool.submit_cleanup(ran.append, "cleanup")
    cancelled_cleanup = pool.submit_cleanup(ran.append, "cleanup nobody waits for")[0]
    assert cancelled_cleanup.cancel()  # a caller that stopped waiting: the cleanup runs all the same
    shutdown = threading.Thread(target=pool.shutdown)
    shutdown.start()
    while not (unpinned.cancelled() and pinned.cancelled()):  # the shutdown has begun; it waits for the running call
        assert shutdown.is_alive()
    assert made.closed == [] and ran == []
    gate.may_end.set()
    shutdown.join(WAIT_LIMIT_TIME)
    assert not shutdown.is_alive()
    assert running.result(0) in made.ids
    assert ran == ["cleanup", "cleanup nobody waits for"] and cleanup.done()
    assert made.closed == [worker_id]
    with pytest.raises(RuntimeError, match="closed"):
        submitted(pool, thread_of, None)
    with pytest.raises(RuntimeError, match="closed"):
        pool.submit_cleanup(ran.append, "late")


async def test_an_awaited_call_that_the_shutdown_drops_raises_runtime_error() -> None:
    """Its caller gets the error of a call after the shutdown instead of waiting for a call that never runs; not
    a `CancelledError`: nobody cancelled the caller, and a task group ignores a child that ends so."""
    with pool_of(1, Workers()) as pool:
        gate, running = held(pool)  # the one thread is busy
        waiting = asyncio.create_task(pool.run(thread_of, None), eager_start=True)  # its call is queued
        shutdown = asyncio.create_task(asyncio.to_thread(pool.shutdown))
        with pytest.raises(RuntimeError, match="closed"):
            await asyncio.wait_for(waiting, WAIT_LIMIT_TIME)
        gate.may_end.set()
        await shutdown  # it waited for the running call
        assert running.done()


async def test_an_awaited_call_never_runs_once_its_caller_is_cancelled_while_it_waits() -> None:
    """From the moment `cancel()` returns, not only once the caller's task has seen the cancellation: the test
    keeps the event loop to itself (it waits on the futures) until the pool thread is past the call."""
    ran: list[str] = []
    with pool_of(1, Workers()) as pool:
        gate, running = held(pool)  # the one thread is busy
        waiting = asyncio.create_task(pool.run(ran.append, "cancelled"), eager_start=True)  # its call is queued
        waiting.cancel()
        gate.may_end.set()
        running.result(WAIT_LIMIT_TIME)
        submitted(pool, ran.append, "later").result(WAIT_LIMIT_TIME)  # behind the cancelled one, on the one thread
        assert ran == ["later"]
        with pytest.raises(asyncio.CancelledError):
            await waiting


def test_the_caller_of_a_dropped_call_is_told_outside_the_pools_lock() -> None:
    """It may use the pool, which is shut down by then."""
    pool = PinningPool(1, "test", Workers())
    gate, _ = held(pool)  # the one thread is busy
    waiting = submitted(pool, thread_of, None)
    told = threading.Event()

    def submit_again(_: Future[int]) -> None:
        with pytest.raises(RuntimeError, match="closed"):
            submitted(pool, thread_of, None)
        told.set()

    waiting.add_done_callback(submit_again)
    shutdown = threading.Thread(target=pool.shutdown, daemon=True)
    shutdown.start()
    try:
        assert told.wait(WAIT_LIMIT_TIME), "the caller was told under the pool's lock"
    finally:
        gate.may_end.set()
    shutdown.join(WAIT_LIMIT_TIME)
    assert waiting.cancelled()


class CallFailed(Exception):
    pass


@pytest.mark.parametrize("fails", [False, True], ids=["result", "error"])
async def test_a_result_or_error_for_a_caller_that_left_is_discarded(fails: bool) -> None:
    """The caller is cancelled while its call runs, so its future is done when the result or error arrives:
    setting it would raise in a callback of the event loop, which only tells its exception handler."""
    reported: list[object] = []
    asyncio.get_running_loop().set_exception_handler(lambda _, context: reported.append(context))
    made = Workers()
    gate = Gate()

    def call(_: None) -> int:
        thread = gate(None)
        if fails:
            raise CallFailed
        return thread

    with pool_of(1, made) as pool:
        left = asyncio.create_task(pool.run(call, None))
        assert await asyncio.to_thread(gate.running.wait, WAIT_LIMIT_TIME)
        left.cancel()
        with pytest.raises(asyncio.CancelledError):
            await left
        gate.may_end.set()
        # a later call on the one thread: when it comes back, the event loop has been told of the first one
        assert await asyncio.wait_for(pool.run(thread_of, None), WAIT_LIMIT_TIME) in made.ids
        assert reported == []


def test_a_result_after_its_event_loop_closed_is_discarded() -> None:
    """The thread that ran the call goes on taking calls (the loop is gone, nobody waits for the result)."""
    made = Workers()
    gate = Gate()

    async def leave_it_running(pool: PinningPool) -> asyncio.Task[int]:
        awaiting = asyncio.create_task(pool.run(gate, None))
        assert await asyncio.to_thread(gate.running.wait, WAIT_LIMIT_TIME)
        return awaiting  # not awaited: the loop's end cancels it

    with pool_of(1, made) as pool:
        left = asyncio.run(leave_it_running(pool))
        assert left.cancelled()
        gate.may_end.set()  # its result arrives at a closed loop
        assert submitted(pool, thread_of, None).result(WAIT_LIMIT_TIME) in made.ids


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
    assert sorted(str(error) for error in info.value.exceptions) == sorted(
        worker_id.token for worker_id in made.failing
    )
    assert sorted(made.closed, key=str) == sorted(made.ids.values(), key=str)
    assert not [thread for thread in threading.enumerate() if thread.ident in threads]
