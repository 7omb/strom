"""`ThreadBackend`: a backend of threads of this interpreter, for "io" and "cpu", and its config `Threads`."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import final, override

from strom._runtime.backends import StreamingBackend, WorkerId
from strom._runtime.iterator_registry import close_unreleased, holds_iterators, init_worker, release_scope
from strom._runtime.pinning_pool import PinningPool, Worker
from strom._runtime.worker_handles.process_handles import init_handles
from strom._validation import check_positive


@final
class _ThreadWorker(Worker):
    """A thread of this interpreter: it runs its calls itself, with an iterator registry of its own (so
    `affinity` names the thread: an iterator stays on the thread that opened it) and this process's worker
    handles (one per process, shared by the threads)."""

    def __init__(self, worker_id: WorkerId) -> None:
        init_worker(worker_id)
        init_handles()

    @override
    def call[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        return fn(arg)

    @override
    def holds_state(self) -> bool:
        return holds_iterators()

    @override
    def close(self) -> None:
        num_left = close_unreleased()
        if num_left:  # every run releases its scope, and the shutdown runs the releases still queued
            raise AssertionError(f"{num_left} io_stage iterators were not released before their pool thread ended")


@final
class ThreadBackend(StreamingBackend):
    """A backend of up to `workers` threads of this interpreter (`PinningPool`), named `name`_0, ...

    Every call with `affinity` runs on that thread, behind what it runs; a release is pinned to every thread,
    so it closes a scope's iterators after the pool tasks still running there, on the threads that opened
    them."""

    def __init__(self, workers: int, name: str) -> None:
        self._pool = PinningPool(workers, name, _ThreadWorker)

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A, *, affinity: WorkerId | None = None) -> B:
        return await self._pool.run(fn, arg, affinity)

    @override
    def release(self, scope: str) -> None:
        self._pool.submit_cleanup(release_scope, scope)

    @override
    async def aclose(self) -> None:
        await asyncio.to_thread(self._pool.shutdown)


# ---- its config: creates the backend when called (on first use of its `Pools`)
@final
@dataclass(frozen=True, kw_only=True)
class Threads:
    """A backend of `workers` threads (thread names start with `name`: set it to tell pools apart); for "io"
    and "cpu" (parallel CPU work only on the free-threaded build)."""

    workers: int
    name: str = "threads"

    def __post_init__(self) -> None:
        check_positive("workers", self.workers)

    def __call__(self) -> ThreadBackend:
        return ThreadBackend(self.workers, self.name)
