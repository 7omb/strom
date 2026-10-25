"""Backends: what runs the pool tasks of one resource. The interface for implementers (`strom.backends`); the
built-in backends implement it in `executor_backend`, `thread_backend` and `process_backend`."""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import override


@dataclass(frozen=True, slots=True)
class WorkerId:
    """A pool worker, unique per worker (a thread, a process or a remote worker): where `affinity` sends a
    pool task, and whose registry holds the iterators it opened (`strom._runtime.iterator_registry`)."""

    token: str


class Backend(ABC):
    """Runs the pool tasks of one resource: created when a `Pools` first needs it, used within one event loop,
    closed once by `aclose`.

    Pool tasks run at most once (no retries). A backend whose workers do not share this interpreter's memory
    pickles functions, arguments, results and errors; the user's exception must arrive as itself. A backend
    knows nothing of runs: what a run adds to its pool tasks (timing them, skipping them once it has failed)
    is inside the function it passes (`strom._interpreters.offloaders`). For "cpu" (`cpu_stage`: one pool
    task per input); "io" needs a `StreamingBackend`."""

    @abstractmethod
    async def run[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        """fn(arg) as one pool task: its result, or the error it raised, whatever they are.

        Cancelling the caller cancels the task if it has not been dispatched (a backend may dispatch some
        ahead, as a `ProcessPoolExecutor` does); a dispatched one finishes. A broken backend or a lost worker
        raises; the backend may replace its workers for later tasks."""

    @abstractmethod
    async def aclose(self) -> None:
        """Final: cancels queued pool tasks, waits for running ones; any later use raises `RuntimeError`. Must
        not block the event loop (`Pools` shields it)."""

    async def close_handle(self, key: str) -> None:
        """Closes the worker handle `key` in every process of this backend's workers other than this one, at
        the end of its `worker_handle` block (this process's handle the block closes itself).

        Workers that use handles call `init_handles` (e.g. as a thread initializer); in each of their processes
        this runs `close_process_handle(key)`, which waits for the uses in flight there and raises the error of
        the close. Raises an `ExceptionGroup` of those errors, each with a note naming its worker; a worker
        that is gone counts as closed. Waits until every process has closed it, without blocking the event
        loop. The default does nothing: for workers that are threads of this process, or that use no
        handles."""
        return  # a hook with a default, not abstract: most backends need none


class StreamingBackend(Backend):
    """A backend for "io" (`io_stage`): pool tasks run on a given worker, and what a run left in its workers
    can be released.

    `io_stage` keeps each iterator in the worker that opened it (`strom._runtime.iterator_registry`), under
    the scope of its run, and runs every later call of it with `affinity` set to that worker. A backend of
    threads sharing one registry honours `affinity` trivially."""

    @override
    @abstractmethod
    async def run[A, B](self, fn: Callable[[A], B], arg: A, *, affinity: WorkerId | None = None) -> B:
        """`Backend.run`, on the worker `affinity` (None: any worker)."""

    @abstractmethod
    def release(self, scope: str) -> None:
        """Runs `release_scope(scope)` on every worker that may hold iterators of `scope` (once for workers
        sharing a registry), each after the pool tasks still running there; returns without waiting for it.
        Errors are ignored; best effort for a worker that is gone. A release still queued when the backend
        closes runs then; after `aclose` it raises `RuntimeError`.

        A run calls it once, at its end: its callers have all returned or were cancelled, and a cancelled
        task that had not started never runs, so after the running ones nothing can register an iterator of
        `scope` any more."""
