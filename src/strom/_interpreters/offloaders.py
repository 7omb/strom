"""The offloader: how a step of a streaming run runs blocking functions on the run's backends, measured or
not: the items of a `cpu_stage` listed in one pool task, those of an `io_stage` streamed one per pool task;
the run's failure flag, which skips its pool tasks once it has failed; and the run's scope, which releases
what its `io_stage` steps left in the workers.

Only runs offload: the reference semantics evaluates a leaf where it stands (`strom._interpreters.reference`).
What a run adds to a pool task (the failure check, the timing) wraps the function it gives the backend, so a
backend knows nothing of runs."""

import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable, Iterable
from functools import partial
from time import perf_counter, thread_time
from typing import NamedTuple, final, override

from strom._metrics.events import PoolTaskFinished, Recorder, StepId
from strom._runtime.backends import WorkerId
from strom._runtime.iterator_registry import next_item, open_iterator
from strom._runtime.pools import RunBackends


class PoolTaskSkipped(Exception):
    """Raised instead of starting a pool task of a run that has failed (`_guarded`).

    Internal to a run: it never reaches the user; the run's own error ends it. (How a run handles it:
    `strom._interpreters.steps`.)"""


@final
class FailureFlag:
    """A run's failure flag: set when the run fails; its pool tasks that have not started are then skipped
    (`_guarded`).

    Pool workers that share this process's memory (threads) see it and set it. A pool task pickled for another
    process takes a copy along: it is skipped there if the flag was set when it was pickled, and what it sets
    stays there. A plain attribute, no lock: it only ever goes from False to True."""

    __slots__ = ("_failed",)

    def __init__(self) -> None:
        self._failed = False

    def is_set(self) -> bool:
        return self._failed

    def set(self) -> None:
        self._failed = True


def _guarded[A, B](failed: FailureFlag, fn: Callable[[A], B], arg: A) -> B:
    """Executed in the pool worker: fn(arg), unless the run has failed (`PoolTaskSkipped`).

    Checked in the worker: where it shares the run's memory, a failing function sets the flag in its own
    thread, so the next queued pool task sees it (no race with the event loop). Top-level, so that
    partial(_guarded, failed, fn) is picklable."""
    if failed.is_set():
        raise PoolTaskSkipped
    try:
        return fn(arg)
    except BaseException:
        failed.set()
        raise


@final
class RunScope:
    """The token a run's `io_stage` iterators are registered under in the pool workers; the runner releases
    them in one go at the run's end (`RunBackends.release`, `StreamingBackend.release`).

    The token is made on first use: a run without `io_stage` has nothing to release."""

    __slots__ = ("_token",)

    def __init__(self) -> None:
        self._token: str | None = None

    def token(self) -> str:
        if self._token is None:
            self._token = uuid.uuid4().hex
        return self._token

    def used(self) -> str | None:
        """The token, if the run registered under it (None: nothing to release)."""
        return self._token


class PoolCalls(ABC):
    """One pool task on the run's backend of a resource; a decorator adds to every call (`_Measured`).

    An ABC: its two implementations are this module's. mypy and pyright reject an override that is not
    generic; ty does not (`.claude/rules/typing.md`)."""

    @abstractmethod
    async def cpu[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        """fn(arg) on the "cpu" backend."""

    @abstractmethod
    async def io[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None) -> B:
        """fn(arg) on the "io" backend, on the worker `affinity` (None: any)."""


def step_offloader(
    backends: RunBackends, failed: FailureFlag, scope: RunScope, recorder: Recorder | None, step_id: StepId
) -> Offloader:
    """The offloader of one step occurrence: measured if the run records (`recorder`)."""
    calls: PoolCalls = _OnBackends(backends, failed)
    if recorder is not None:
        calls = _Measured(calls, recorder, step_id)
    return Offloader(calls, scope)


@final
class _OnBackends(PoolCalls):
    """The run's backends; every call is guarded by the run's failure flag (`_guarded`)."""

    __slots__ = ("_backends", "_failed")

    def __init__(self, backends: RunBackends, failed: FailureFlag) -> None:
        self._backends = backends
        self._failed = failed

    @override
    async def cpu[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        guarded: Callable[[A], B] = partial(_guarded, self._failed, fn)
        return await self._backends.cpu().run(guarded, arg)  # resolved per call: the pools may be closed

    @override
    async def io[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None) -> B:
        guarded: Callable[[A], B] = partial(_guarded, self._failed, fn)
        return await self._backends.io().run(guarded, arg, affinity=affinity)


@final
class _Measured(PoolCalls):
    """`inner`, recording a `PoolTaskFinished` of `step_id` per completed pool task, timed in the worker.

    A result whose recording fails is dropped like that of a cancelled caller: the run's scope releases what
    it left in its worker."""

    __slots__ = ("_inner", "_recorder", "_step_id")

    def __init__(self, inner: PoolCalls, recorder: Recorder, step_id: StepId) -> None:
        self._inner = inner
        self._recorder = recorder
        self._step_id = step_id

    @override
    async def cpu[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        submitted_at = perf_counter()
        timed_fn: Callable[[A], _Timed[B]] = partial(_timed, fn)
        timed = await self._inner.cpu(timed_fn, arg)
        self._record(submitted_at, timed)
        return timed.result

    @override
    async def io[A, B](self, fn: Callable[[A], B], arg: A, affinity: WorkerId | None) -> B:
        submitted_at = perf_counter()
        timed_fn: Callable[[A], _Timed[B]] = partial(_timed, fn)
        timed = await self._inner.io(timed_fn, arg, affinity)
        self._record(submitted_at, timed)
        return timed.result

    def _record[B](self, submitted_at: float, timed: _Timed[B]) -> None:
        self._recorder(
            PoolTaskFinished(self._step_id, submitted_at, perf_counter(), timed.running_time, timed.cpu_time)
        )


class _Timed[B](NamedTuple):
    """The result of a pool task with its running time and CPU time.

    The times are durations, so they stay valid across processes."""

    result: B
    running_time: float
    cpu_time: float


def _timed[A, B](fn: Callable[[A], B], arg: A) -> _Timed[B]:
    """Executed in the pool worker: fn(arg), timed (wall time and the worker thread's CPU time).

    Top-level so that partial(_timed, fn) is picklable."""
    started_at, cpu_started_at = perf_counter(), thread_time()
    result = fn(arg)
    return _Timed(result, perf_counter() - started_at, thread_time() - cpu_started_at)


def _listed[A, B](fn: Callable[[A], Iterable[B]], item: A) -> list[B]:
    """Executed in the pool worker. Top-level so that partial(_listed, fn) is picklable."""
    return list(fn(item))


@final
class Offloader:
    """How one step occurrence runs blocking functions: as `calls`, pool tasks on the run's backends.

    An `io_stage` iterator stays in the worker that opened it (`strom._runtime.iterator_registry`), under the
    run's scope: only its key comes back, and every later call of the key goes to that worker."""

    __slots__ = ("_calls", "_scope")

    def __init__(self, calls: PoolCalls, scope: RunScope) -> None:
        self._calls = calls
        self._scope = scope

    async def listed[A, B](self, fn: Callable[[A], Iterable[B]], item: A) -> list[B]:
        """The items of fn(item), listed in ONE pool task on the "cpu" backend (`cpu_stage`)."""
        return await self._calls.cpu(partial(_listed, fn), item)

    async def streamed[A, B](self, fn: Callable[[A], Iterable[B]], item: A) -> AsyncGenerator[B]:
        """The items of fn(item) from the "io" backend, streamed (`io_stage`): one pool task per item of an
        iterator; a list or a tuple comes whole, in the one pool task that calls fn.

        The first pool task also calls fn(item), and one more finds an iterator's end, so no pool worker is
        held between items (e.g. while downstream applies backpressure). An iterator not run to its end
        (closed early, or its first item never received) is closed when the run's scope is released, in its
        worker."""
        opened = await self._calls.io(partial(open_iterator, self._scope.token(), fn), item, None)
        for out in opened.items:
            yield out
        key = opened.key
        if key is None:  # a list, a tuple or an iterator that ended at once: nothing registered
            return
        worker = key.worker
        # the ignore: a false positive of ty for `next_item` (2026-11-11, see `.claude/rules/typing.md`)
        while (next_one := await self._calls.io(next_item, key, worker)) is not None:  # ty: ignore[invalid-argument-type]
            yield next_one.item
