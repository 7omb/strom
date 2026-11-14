"""`PinningPool`: threads that take their calls from one shared FIFO and from a FIFO each, so that a call runs on
any of them or on the one it is pinned to; and `Worker`, what a thread runs its calls with. The part the thread
and the process backend are built from (each holds one, with workers of its own).

A `concurrent.futures` executor hands a call to any worker. With a FIFO per thread, a call can be addressed: an
`io_stage` iterator stays on the thread that opened it (`affinity`), and "on that worker, after what it runs
now" is a call pinned to it: the release of a run's scope, the close of a worker handle (cleanups). A thread
takes the older of its two next calls (the one pinned to it, the unpinned one), so neither kind starves the other.

A thread is busy (it runs a call, or was handed one) or idle (it waits in `_idle_stateless` or `_idle_stateful`
until a call is handed to it); the queues and these states change only under the pool's lock.

A call's result or error goes to its caller (`_Caller`). The callers of `run` await it: the pool thread hands it
to the caller's event loop, which sets it on an asyncio future, without a `concurrent.futures.Future` between
them (`docs/decisions/worker-pool.md`)."""

import asyncio
import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Final, final, override

from strom._runtime.backends import BACKEND_CLOSED, WorkerId


class Worker(ABC):
    """What one thread of a `PinningPool` runs its calls with: created in the thread when it starts, closed in
    it when it ends, and used by that thread only."""

    @abstractmethod
    def call[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        """fn(arg) as this worker runs it: its result, or the error it raised."""

    def clean_up[A](self, fn: Callable[[A], None], arg: A) -> None:
        """A cleanup pinned to this worker (`PinningPool.submit_cleanup`): fn(arg), unless nothing here can need
        it any more."""
        self.call(fn, arg)

    def holds_state(self) -> bool:
        """Whether this worker holds what later pinned calls will need (an open iterator): an unpinned call
        then prefers another idle thread, so that those calls need not wait behind it."""
        return False

    def close(self) -> None:
        """At the thread's end, after its last call; an error is raised by the pool's `shutdown`."""
        return


@final
class _Call:
    """A call until a thread takes it: how a worker runs it, how the shutdown drops it (None: a cleanup, which
    the shutdown keeps), and, once it is queued, its number in the order of arrival (`arrival`, given under the
    pool's lock)."""

    __slots__ = ("arrival", "drop", "run")

    def __init__(self, run: Callable[[Worker], None], drop: Callable[[], None] | None) -> None:
        self.run: Final = run
        self.drop: Final = drop
        self.arrival = 0


class _Caller[B](ABC):
    """The caller of a call, as the pool sees it (`PinningPool._submit`): who gets the call's result or error.
    Told by the thread that takes the call, or by the shutdown that drops it while it waits, never under the
    pool's lock (a caller may use the pool).

    The thread asks `waits` once, as it takes the call (an implementation may change its state there), and
    sets the result or the exception of a call it ran. No method raises: an error would end the pool thread
    before it closes its worker."""

    __slots__ = ()

    @abstractmethod
    def waits(self) -> bool:
        """Whether it still waits for the call (False: the call never runs)."""

    @abstractmethod
    def set_result(self, result: B) -> None:
        """The call returned `result`."""

    @abstractmethod
    def set_exception(self, error: BaseException) -> None:
        """The call raised `error`."""

    @abstractmethod
    def drop(self) -> None:
        """The shutdown took the call out of its queue: it never runs."""


@final
class _Awaiting[B](_Caller[B]):
    """A caller that awaits its call on an event loop (`PinningPool.run`): the result or error is set on `future`
    in the loop's thread, unless it stopped waiting (the future is done) or the loop is closed (nobody waits).
    A dropped call raises the error of a call after the shutdown."""

    __slots__ = ("future", "loop")

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop: Final = loop
        self.future: Final[asyncio.Future[B]] = loop.create_future()

    @override
    def waits(self) -> bool:
        # read in the pool thread, though asyncio's futures are not thread-safe: one read of the state, which
        # `task.cancel()` of the caller sets at once (`docs/decisions/worker-pool.md`)
        return not self.future.done()

    @override
    def set_result(self, result: B) -> None:
        self._in_loop(_set_result_if_pending, self.future, result)

    @override
    def set_exception(self, error: BaseException) -> None:
        self._in_loop(_set_exception_if_pending, self.future, error)

    @override
    def drop(self) -> None:
        self.set_exception(RuntimeError(BACKEND_CLOSED))

    def _in_loop[*Ts](self, callback: Callable[[*Ts], object], *args: *Ts) -> None:
        try:  # noqa: SIM105 (once per call: `contextlib.suppress` costs a context manager each time)
            self.loop.call_soon_threadsafe(callback, *args)
        except RuntimeError:
            pass  # the loop is closed: nobody waits for the call


def _set_result_if_pending[B](future: asyncio.Future[B], result: B) -> None:
    if not future.done():
        future.set_result(result)


def _set_exception_if_pending[B](future: asyncio.Future[B], error: BaseException) -> None:
    if not future.done():
        future.set_exception(error)


def _calling[A, B](fn: Callable[[A], B], arg: A, caller: _Caller[B]) -> Callable[[Worker], None]:
    def run(worker: Worker) -> None:
        if not caller.waits():
            return  # its caller stopped waiting: it never runs
        try:
            result = worker.call(fn, arg)
        except BaseException as error:
            caller.set_exception(error)
        else:
            caller.set_result(result)

    return run


def _cleaning_up[A](fn: Callable[[A], None], arg: A, future: Future[None]) -> Callable[[Worker], None]:
    def run(worker: Worker) -> None:
        caller_waits = future.set_running_or_notify_cancel()  # a caller that stopped waiting: it runs all the same
        try:
            worker.clean_up(fn, arg)
        except BaseException as error:
            if caller_waits:
                future.set_exception(error)
        else:
            if caller_waits:
                future.set_result(None)

    return run


@final
class _Thread:
    """One thread of the pool: its id, the calls pinned to it, and how a call is handed to it while it is idle
    (`handed`, then `wake` is released)."""

    __slots__ = ("close_error", "handed", "id", "os_thread", "pinned", "wake")

    def __init__(self, worker_id: WorkerId, first: _Call, target: Callable[[_Thread], None], name: str) -> None:
        self.id: Final = worker_id
        self.pinned: deque[_Call] = deque()
        self.handed: _Call | None = first
        self.wake: Final = threading.Lock()  # held while nothing is handed over: an idle thread waits for it
        self.wake.acquire()
        self.os_thread: Final = threading.Thread(target=target, args=(self,), name=name, daemon=True)
        self.close_error: BaseException | None = None


@final
class PinningPool:
    """Up to `workers` threads, started on demand (named `name`_0, ...), each with the `Worker` that
    `new_worker(id)` creates in it (`new_worker` must not raise: what can fail does so in the worker's `call`).

    An unpinned call goes to an idle thread whose worker holds nothing pinned calls will need (a stateless one),
    else to a new thread, else to an idle thread whose worker does (a stateful one), else it waits in the shared
    FIFO; a busy thread then takes its calls, pinned and unpinned, in the order they arrived. (A worker's answer
    is taken when its thread goes idle: only its own calls change it.)"""

    def __init__(self, workers: int, name: str, new_worker: Callable[[WorkerId], Worker]) -> None:
        self._max_threads: Final = workers
        self._name: Final = name
        self._new_worker: Final = new_worker
        self._token: Final = uuid.uuid4().hex  # of this pool, in the ids of its workers
        self._lock: Final = threading.Lock()
        self._unpinned: deque[_Call] = deque()
        self._threads: dict[WorkerId, _Thread] = {}
        # the idle threads, stateful if their worker holds state (`Worker.holds_state`); as ordered sets: the one
        # that went idle last is taken first
        self._idle_stateless: dict[_Thread, None] = {}
        self._idle_stateful: dict[_Thread, None] = {}
        self._num_arrivals = 0  # of the calls queued so far: the next one's `arrival`
        self._shut_down = False

    async def run[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None = None) -> B:
        """fn(arg) on any thread, or on the thread `affinity` (`LookupError` if the pool has none of that id),
        behind what that thread runs and the calls that waited for it before, awaited: its result, or the error
        it raised. A call whose caller is cancelled while it waits never runs. `RuntimeError` once the pool is
        shut down, also for a call the shutdown dropped while it waited."""
        caller: _Awaiting[B] = _Awaiting(asyncio.get_running_loop())  # not `_Awaiting[B](...)`: no alias per call
        self._submit(fn, arg, caller, affinity)
        return await caller.future

    def _submit[A, B](self, fn: Callable[[A], B], arg: A, caller: _Caller[B], affinity: WorkerId | None = None) -> None:
        """`run`, with the result or error going to `caller`."""
        call = _Call(_calling(fn, arg, caller), caller.drop)
        with self._lock:
            if self._shut_down:
                raise RuntimeError(BACKEND_CLOSED)
            if affinity is None:
                self._place(call)
            else:
                thread = self._threads.get(affinity)
                if thread is None:
                    raise LookupError(f"no worker {affinity.token} in this pool: lost, or the call was misrouted")
                self._pin(thread, call)

    def submit_cleanup[A](self, fn: Callable[[A], None], arg: A) -> list[Future[None]]:
        """fn(arg) pinned to every thread started so far (a later one holds nothing to clean up), each behind
        what that thread runs and the calls that waited for it before. A cleanup is never dropped: the shutdown
        runs those still queued, and cancelling its future only ends the wait for it. `RuntimeError` once the
        pool is shut down."""
        futures: list[Future[None]] = []
        with self._lock:
            if self._shut_down:
                raise RuntimeError(BACKEND_CLOSED)
            for thread in self._threads.values():
                future: Future[None] = Future()
                self._pin(thread, _Call(_cleaning_up(fn, arg, future), None))
                futures.append(future)
        return futures

    def _place(self, call: _Call) -> None:
        """Under `_lock`: hands an unpinned call to a thread (an idle or a new one), or queues it."""
        if self._idle_stateless:
            self._hand(self._idle_stateless.popitem()[0], call)
        elif len(self._threads) < self._max_threads:
            self._start_thread(call)
        elif self._idle_stateful:
            self._hand(self._idle_stateful.popitem()[0], call)
        else:
            self._queue(self._unpinned, call)

    def _pin(self, thread: _Thread, call: _Call) -> None:
        """Under `_lock`: `call` for `thread`: handed over if it is idle, else behind what is pinned to it."""
        was_idle = self._idle_stateless.pop(thread, 0) is None or self._idle_stateful.pop(thread, 0) is None
        if was_idle:
            self._hand(thread, call)
        else:
            self._queue(thread.pinned, call)

    def _queue(self, fifo: deque[_Call], call: _Call) -> None:
        """Under `_lock`: `call` waits in `fifo`, numbered in the order of arrival over all FIFOs."""
        call.arrival = self._num_arrivals
        self._num_arrivals += 1
        fifo.append(call)

    def _hand(self, thread: _Thread, call: _Call) -> None:
        """Under `_lock`: wakes the idle `thread` (taken out of the idle threads already) with `call`."""
        thread.handed = call
        thread.wake.release()

    def _start_thread(self, first: _Call) -> None:
        """Under `_lock` (so that the shutdown joins only started threads): a new thread, with `first` as its
        first call."""
        number = len(self._threads)
        thread = _Thread(WorkerId(f"{self._token}-{number}"), first, self._serve, f"{self._name}_{number}")
        thread.os_thread.start()  # before it is registered: one that cannot start is no thread of the pool
        self._threads[thread.id] = thread

    def _serve(self, thread: _Thread) -> None:
        """A thread of the pool: one call after another, then the close of its worker."""
        worker = self._new_worker(thread.id)
        call, thread.handed = thread.handed, None  # its first call
        while call is not None:
            call.run(worker)
            call = None  # while it waits for its next call, it keeps nothing of this one (argument, result)
            call = self._take(thread, worker)
        try:
            worker.close()
        except BaseException as error:
            thread.close_error = error

    def _take(self, thread: _Thread, worker: Worker) -> _Call | None:
        """The next call of `thread`: the older of the one pinned to it and the unpinned one (so neither kind
        starves the other); without any it waits until one is handed to it. None once the pool is shut down and
        nothing is pinned to it any more."""
        while True:
            with self._lock:
                pinned, unpinned = thread.pinned, self._unpinned  # the shutdown empties `unpinned`
                if pinned and (not unpinned or pinned[0].arrival < unpinned[0].arrival):
                    return pinned.popleft()
                if unpinned:
                    return unpinned.popleft()
                if self._shut_down:
                    return None
                (self._idle_stateful if worker.holds_state() else self._idle_stateless)[thread] = None
            thread.wake.acquire()  # until a call is handed over (set before the release), or the shutdown wakes it
            handed, thread.handed = thread.handed, None
            if handed is not None:
                return handed

    def shutdown(self) -> None:
        """Final: later calls raise `RuntimeError`. Drops the queued calls, keeps the cleanups; every thread
        finishes its running call and its cleanups, closes its worker and ends. Waits for them and raises the
        errors of the closes (several as a group). Blocks: run it in a thread."""
        with self._lock:
            self._shut_down = True
            drops = [call.drop for call in self._unpinned if call.drop is not None]  # no cleanup waits there
            self._unpinned.clear()
            for thread in self._threads.values():
                kept: deque[_Call] = deque()
                for call in thread.pinned:
                    if call.drop is None:
                        kept.append(call)
                    else:
                        drops.append(call.drop)
                thread.pinned = kept
            idle = [*self._idle_stateless, *self._idle_stateful]
            self._idle_stateless.clear()
            self._idle_stateful.clear()
            for thread in idle:
                thread.wake.release()  # nothing handed over: it takes its cleanups and ends
            threads = list(self._threads.values())
        for drop in drops:  # out of the queues already, and outside the lock: a caller may use the pool
            drop()
        errors: list[BaseException] = []
        for thread in threads:
            thread.os_thread.join()
            if thread.close_error is not None:
                errors.append(thread.close_error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("closing the workers of a pool failed", errors)
