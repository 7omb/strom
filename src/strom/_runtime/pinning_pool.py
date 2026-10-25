"""`PinningPool`: threads that take their calls from one shared FIFO and from a FIFO each, so that a call runs on
any of them or on the one it is pinned to; and `Worker`, what a thread runs its calls with. The part the thread
and the process backend are built from (each holds one, with workers of its own).

A `concurrent.futures` executor hands a call to any worker. With a FIFO per thread, a call can be addressed: an
`io_stage` iterator stays on the thread that opened it (`affinity`), and "on that worker, after what it runs
now" is a call pinned to it: the release of a run's scope, the close of a worker handle (cleanups). A thread
takes the older of its two next calls (the one pinned to it, the shared one), so neither kind starves the other.

A thread is busy (it runs a call, or was handed one) or idle (it waits in `_idle_free` or `_idle_holding` until a
call is handed to it); the queues and these states change only under the pool's lock."""

import threading
import uuid
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Final, final

from strom._runtime.backends import WorkerId

_POOL_CLOSED = "the backend is closed (its Pools is closed)"


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

    def holds_pinned(self) -> bool:
        """Whether this worker holds what later pinned calls will need (an open iterator): a call without
        affinity then prefers another idle thread, so that those calls need not wait behind it."""
        return False

    def close(self) -> None:
        """At the thread's end, after its last call; an error is raised by the pool's `shutdown`."""
        return


@final
class _Queued:
    """A call that waits for a thread: how a worker runs it, how the shutdown cancels it, whether the shutdown
    keeps it (a cleanup), and its number in the order of arrival (given under the pool's lock)."""

    __slots__ = ("cancel", "kept", "number", "run")

    def __init__(self, run: Callable[[Worker], None], cancel: Callable[[], bool], kept: bool) -> None:
        self.run: Final = run
        self.cancel: Final = cancel
        self.kept: Final = kept
        self.number = 0


def _calling[A, B](fn: Callable[[A], B], arg: A, future: Future[B]) -> Callable[[Worker], None]:
    def run(worker: Worker) -> None:
        if not future.set_running_or_notify_cancel():
            return  # cancelled while it waited: it never runs
        try:
            result = worker.call(fn, arg)
        except BaseException as error:
            future.set_exception(error)
        else:
            future.set_result(result)

    return run


def _cleaning_up[A](fn: Callable[[A], None], arg: A, future: Future[None]) -> Callable[[Worker], None]:
    def run(worker: Worker) -> None:
        heard = future.set_running_or_notify_cancel()  # a caller that stopped waiting: it runs all the same
        try:
            worker.clean_up(fn, arg)
        except BaseException as error:
            if heard:
                future.set_exception(error)
        else:
            if heard:
                future.set_result(None)

    return run


@final
class _Thread:
    """One thread of the pool: its id, the calls pinned to it, and how a call is handed to it while it is idle
    (`handed`, then `wake` is released)."""

    __slots__ = ("close_error", "handed", "id", "pinned", "thread", "wake")

    def __init__(self, worker_id: WorkerId, first: _Queued, run: Callable[[_Thread], None], name: str) -> None:
        self.id: Final = worker_id
        self.pinned: deque[_Queued] = deque()
        self.handed: _Queued | None = first
        self.wake: Final = threading.Lock()  # held while nothing is handed over: an idle thread waits for it
        self.wake.acquire()
        self.thread: Final = threading.Thread(target=run, args=(self,), name=name, daemon=True)
        self.close_error: BaseException | None = None


@final
class PinningPool:
    """Up to `workers` threads, started on demand (named `name`_0, ...), each with the `Worker` that
    `new_worker(id)` creates in it (`new_worker` must not raise: what can fail does so in the worker's `call`).

    A call without affinity goes to an idle thread whose worker holds nothing pinned calls will need, else to a
    new thread, else to an idle thread whose worker does, else it waits in the shared FIFO; a busy thread then
    takes its calls, pinned and shared, in the order they arrived. (A worker's answer is taken when its thread
    goes idle: only its own calls change it.)"""

    def __init__(self, workers: int, name: str, new_worker: Callable[[WorkerId], Worker]) -> None:
        self._max_threads: Final = workers
        self._name: Final = name
        self._new_worker: Final = new_worker
        self._token: Final = uuid.uuid4().hex  # of this pool, in the ids of its workers
        self._lock: Final = threading.Lock()
        self._shared: deque[_Queued] = deque()
        self._threads: dict[WorkerId, _Thread] = {}
        # the idle threads, as ordered sets: the one that went idle last is taken first
        self._idle_free: dict[_Thread, None] = {}
        self._idle_holding: dict[_Thread, None] = {}
        self._num_queued = 0  # so far: the next queued call's number
        self._closed = False

    def submit[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None = None) -> Future[B]:
        """fn(arg) on any thread, or on the thread `affinity` (`LookupError` if the pool has none of that id),
        behind what that thread runs and the calls that waited for it before. A call whose future is cancelled
        while it waits never runs. `RuntimeError` once the pool is shut down."""
        future: Future[B] = Future()
        queued = _Queued(_calling(fn, arg, future), future.cancel, kept=False)
        with self._lock:
            if self._closed:
                raise RuntimeError(_POOL_CLOSED)
            if affinity is None:
                self._place(queued)
            else:
                thread = self._threads.get(affinity)
                if thread is None:
                    raise LookupError(f"no worker {affinity.token} in this pool: lost, or the call was misrouted")
                self._pin(thread, queued)
        return future

    def submit_cleanup[A](self, fn: Callable[[A], None], arg: A) -> list[Future[None]]:
        """fn(arg) pinned to every thread started so far (a later one holds nothing to clean up), each behind
        what that thread runs and the calls that waited for it before. A cleanup is never cancelled, neither
        by its future nor by the shutdown, which runs those still queued. `RuntimeError` once the pool is shut
        down."""
        futures: list[Future[None]] = []
        with self._lock:
            if self._closed:
                raise RuntimeError(_POOL_CLOSED)
            for thread in self._threads.values():
                future: Future[None] = Future()
                self._pin(thread, _Queued(_cleaning_up(fn, arg, future), future.cancel, kept=True))
                futures.append(future)
        return futures

    def _place(self, queued: _Queued) -> None:
        """Under `_lock`: hands a call without affinity to a thread (an idle or a new one), or queues it."""
        if self._idle_free:
            self._hand(self._idle_free.popitem()[0], queued)
        elif len(self._threads) < self._max_threads:
            self._start_thread(queued)
        elif self._idle_holding:
            self._hand(self._idle_holding.popitem()[0], queued)
        else:
            self._queue(self._shared, queued)

    def _pin(self, thread: _Thread, queued: _Queued) -> None:
        """Under `_lock`: `queued` for `thread`: handed over if it is idle, else behind what is pinned to it."""
        was_idle = self._idle_free.pop(thread, 0) is None or self._idle_holding.pop(thread, 0) is None
        if was_idle:
            self._hand(thread, queued)
        else:
            self._queue(thread.pinned, queued)

    def _queue(self, fifo: deque[_Queued], queued: _Queued) -> None:
        """Under `_lock`: `queued` waits in `fifo`, numbered in the order of arrival over all FIFOs."""
        queued.number = self._num_queued
        self._num_queued += 1
        fifo.append(queued)

    def _hand(self, thread: _Thread, queued: _Queued) -> None:
        """Under `_lock`: wakes the idle `thread` (taken out of the idle threads already) with `queued`."""
        thread.handed = queued
        thread.wake.release()

    def _start_thread(self, first: _Queued) -> None:
        """Under `_lock` (so that the shutdown joins only started threads): a new thread, with `first` as its
        first call."""
        number = len(self._threads)
        thread = _Thread(WorkerId(f"{self._token}-{number}"), first, self._run, f"{self._name}_{number}")
        thread.thread.start()  # before it is registered: one that cannot start is no thread of the pool
        self._threads[thread.id] = thread

    def _run(self, thread: _Thread) -> None:
        """A thread of the pool: one call after another, then the close of its worker."""
        worker = self._new_worker(thread.id)
        queued, thread.handed = thread.handed, None  # its first call
        while queued is not None:
            queued.run(worker)
            queued = None  # while it waits for its next call, it keeps nothing of this one (argument, result)
            queued = self._take(thread, worker)
        try:
            worker.close()
        except BaseException as error:
            thread.close_error = error

    def _take(self, thread: _Thread, worker: Worker) -> _Queued | None:
        """The next call of `thread`: the older of the one pinned to it and the shared one (so neither kind
        starves the other); without any it waits until one is handed to it. None once the pool is shut down and
        nothing is pinned to it any more."""
        while True:
            with self._lock:
                pinned, shared = thread.pinned, self._shared  # the shutdown empties `shared`
                if pinned and (not shared or pinned[0].number < shared[0].number):
                    return pinned.popleft()
                if shared:
                    return shared.popleft()
                if self._closed:
                    return None
                (self._idle_holding if worker.holds_pinned() else self._idle_free)[thread] = None
            thread.wake.acquire()  # until a call is handed over (set before the release), or the shutdown wakes it
            handed, thread.handed = thread.handed, None
            if handed is not None:
                return handed

    def shutdown(self) -> None:
        """Final: later calls raise `RuntimeError`. Cancels the queued calls, keeps the cleanups; every thread
        finishes its running call and its cleanups, closes its worker and ends. Waits for them and raises the
        errors of the closes (several as a group). Blocks: run it in a thread."""
        with self._lock:
            self._closed = True
            for queued in self._shared:
                queued.cancel()
            self._shared.clear()
            for thread in self._threads.values():
                thread.pinned = deque(queued for queued in thread.pinned if queued.kept or not queued.cancel())
            idle = [*self._idle_free, *self._idle_holding]
            self._idle_free.clear()
            self._idle_holding.clear()
            for thread in idle:
                thread.wake.release()  # nothing handed over: it takes its cleanups and ends
            threads = list(self._threads.values())
        errors: list[BaseException] = []
        for thread in threads:
            thread.thread.join()
            if thread.close_error is not None:
                errors.append(thread.close_error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("closing the workers of a pool failed", errors)
