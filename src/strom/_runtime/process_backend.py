"""`ProcessBackend`: a backend of worker processes, for "cpu", and its config `Processes`; what only it needs:
the worker that forwards a pool thread's calls to a child process, and that child's main function.

Each thread of the backend's `PinningPool` owns one child process and talks to it over a pipe, one call at a
time: the pickled `(fn, arg)`, then the pickled reply `(result, error, traceback text)`. The child serves its
calls in its main thread, so a worker handle is used and closed there, and "between two calls" is simply the
next call of that worker: the close of a handle is a cleanup pinned to each worker (`close_process_handle`).
A call is pickled when its thread takes it, so one that uses a handle whose block has ended fails there
(`WorkerHandle.__reduce__`), and one pickled before runs ahead of the close.

A backend ends its children when it closes. A child is a daemon of this process, which therefore terminates
those of a backend that was never closed at its exit (`multiprocessing` does) instead of waiting for them; for
itself it is none (`serve` clears the flag): a daemon may not start processes, and the functions a worker runs
may, as in a `ProcessPoolExecutor`."""

import asyncio
import multiprocessing
import pickle
import threading
import traceback
from collections.abc import Callable
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from functools import partial
from multiprocessing.connection import Connection
from multiprocessing.context import DefaultContext
from multiprocessing.process import BaseProcess
from multiprocessing.reduction import ForkingPickler
from typing import final, override

from strom._runtime.backends import Backend, WorkerId
from strom._runtime.iterator_registry import init_worker
from strom._runtime.pinning_pool import PinningPool, Worker
from strom._runtime.worker_handles.process_handles import (
    close_all_process_handles,
    close_process_handle,
    init_handles,
)
from strom._validation import check_positive

_END = b""  # the message that ends a child: no pickle is empty

type _Pipe = Connection[bytes, bytes]
"""An end of the pipe between a pool thread and its child: pickles as bytes, both ways."""


# ---- the child's side
def serve(conn: _Pipe, worker: WorkerId) -> None:
    """The main function of a worker process: one call after another from its pipe, in its main thread, until
    the parent ends it (or is gone); then it closes the worker handles it still holds.

    It has an iterator registry and a handle table of its own (`init_worker`, `init_handles`)."""
    multiprocessing.current_process().daemon = False  # a daemon for its parent only (see the module docstring)
    init_worker(worker)
    init_handles()
    try:
        while True:
            try:
                call = conn.recv_bytes()
            except EOFError, OSError, KeyboardInterrupt:  # the parent is gone, or the user interrupts an idle worker
                return
            if call == _END:
                return
            try:
                conn.send_bytes(_reply(call))
            except OSError:  # the parent is gone
                return
    finally:
        close_all_process_handles()


def _reply(call: bytes) -> bytes:
    """The pickled reply to a pickled call: `(result, None, "")`, or `(None, error, its traceback as text)` for
    an error of the function, of unpickling the call or of pickling the result."""
    try:
        unpickled: tuple[Callable[[object], object], object] = pickle.loads(call)  # noqa: S301 (its own pool's)
        fn, arg = unpickled
        return bytes(ForkingPickler.dumps((fn(arg), None, "")))
    except BaseException as error:
        text = traceback.format_exc()
        try:
            reply = bytes(ForkingPickler.dumps((None, error, text)))
            pickle.loads(reply)  # noqa: S301 (its own data): an error must also come back as itself over there
        except Exception:  # an error that cannot be pickled, or not unpickled: its text must do
            stand_in = RuntimeError(f"{type(error).__name__}: {error} (the error itself could not be pickled)")
            return bytes(ForkingPickler.dumps((None, stand_in, text)))
        return reply


class _RemoteTraceback(Exception):
    """The traceback of an error in a worker process, as text: the `__cause__` of that error in this process."""

    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.text = text

    @override
    def __str__(self) -> str:
        return f'\n"""\n{self.text}"""'


# ---- the parent's side
_starting = threading.Lock()
"""Held while a child starts, by all backends: under the `fork` start method, a child started meanwhile by
another pool thread would inherit the first one's end of its pipe, and while it lived the death of the first
would go unnoticed (no end of file)."""


@final
class _ProcessWorker(Worker):
    """A pool thread's worker process: started at the thread's first call, replaced after it died (the call it
    ran then fails with `BrokenProcessPool`; one that died idle ran none), ended when the thread ends. Used by
    its thread only."""

    def __init__(self, context: DefaultContext, worker: WorkerId) -> None:
        self._context = context
        self._id = worker
        self._child: tuple[BaseProcess, _Pipe] | None = None

    @override
    def call[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        # pickled first, in this thread: what cannot be pickled (a lambda, a closed worker handle) fails its own
        # call and costs no process (as bytes: the pickler's buffer must not outlive this statement)
        call = bytes(ForkingPickler.dumps((fn, arg)))
        _, conn = self._child or self._start()
        try:
            try:
                conn.send_bytes(call)
            except OSError:
                # the child ended while it was idle (killed, or interrupted along with this process by the
                # user's Ctrl-C): it ran nothing, so another one takes its place and the call
                self._drop()
                _, conn = self._start()
                conn.send_bytes(call)
            answer = conn.recv_bytes()
        except (EOFError, OSError) as error:
            self._drop()
            raise BrokenProcessPool("a worker process ended while it ran a pool task") from error
        reply: tuple[B, BaseException | None, str] = pickle.loads(answer)  # noqa: S301 (its own child's)
        result, raised, remote_traceback = reply
        if raised is None:
            return result
        raised.__cause__ = _RemoteTraceback(remote_traceback)
        raise raised

    @override
    def clean_up[A](self, fn: Callable[[A], None], arg: A) -> None:
        if self._child is not None and not self._child[0].is_alive():
            self._drop()  # it ended while it was idle: no other one is started for a cleanup
        if self._child is None:
            return  # no process (yet, or any more): nothing is held
        try:
            self.call(fn, arg)
        except BrokenProcessPool:
            return  # gone: what it held went with it

    @override
    def close(self) -> None:
        if self._child is None:
            return
        process, conn = self._child
        try:
            conn.send_bytes(_END)
        except OSError:
            pass  # it is gone already
        process.join()
        conn.close()
        self._child = None

    def _start(self) -> tuple[BaseProcess, _Pipe]:
        with _starting:
            ends: tuple[_Pipe, _Pipe] = self._context.Pipe()
            parent_end, child_end = ends
            process = self._context.Process(target=serve, args=(child_end, self._id), daemon=True)
            process.start()
            child_end.close()  # the child has its own copy: closing it there is the end of this pipe
        child = self._child = process, parent_end
        return child

    def _drop(self) -> None:
        """The pipe to the child broke (it crashed, or was killed): the next call starts another one."""
        if self._child is not None:
            process, conn = self._child
            self._child = None
            conn.close()
            # one that still lives is of no use without its pipe; asked first, so that a child that ended is
            # never signalled (it may have ended long ago, and its process id be another process's by now)
            if process.is_alive():
                process.kill()
            process.join()


@final
class ProcessBackend(Backend):
    """A backend of up to `workers` worker processes, each behind a thread of a `PinningPool` that forwards its
    calls to it (`_ProcessWorker`).

    So its queued calls wait in this process (a cancelled one never starts), a crashed process breaks its own
    call only, and closing a worker handle is a call pinned to every worker, behind what it runs."""

    def __init__(self, workers: int) -> None:
        self._pool = PinningPool(workers, "processes", partial(_ProcessWorker, multiprocessing.get_context()))

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        return await asyncio.wrap_future(self._pool.submit(fn, arg))

    @override
    async def close_handle(self, key: str) -> None:
        closes = self._pool.submit_cleanup(close_process_handle, key)
        results = await asyncio.gather(*map(asyncio.wrap_future, closes), return_exceptions=True)
        errors = [result for result in results if result is not None]
        if errors:
            raise BaseExceptionGroup("closing the worker handle failed in the worker processes", errors)

    @override
    async def aclose(self) -> None:
        await asyncio.to_thread(self._pool.shutdown)


# ---- its config: creates the backend when called (on first use of its `Pools`)
@final
@dataclass(frozen=True, kw_only=True)
class Processes:
    """A backend of `workers` processes (functions, items and results are pickled); for "cpu" only."""

    workers: int

    def __post_init__(self) -> None:
        check_positive("workers", self.workers)

    def __call__(self) -> ProcessBackend:
        return ProcessBackend(self.workers)
