"""`ExecutorBackend`: a backend on an executor of the user's, for "cpu", and its config `FromExecutor`.

Its executor is in one state (`_State`):

    Empty --first use--> Running --broken--> Empty
    Empty, Running --close--> Closed"""

import asyncio
from collections.abc import Callable
from concurrent.futures import BrokenExecutor, Executor
from dataclasses import dataclass
from typing import Final, final, override

from strom._runtime.backends import Backend

_BACKEND_CLOSED = "the backend is closed (its Pools is closed)"


@dataclass(frozen=True, slots=True)
class _Empty:
    """No executor: the next use creates one."""


@dataclass(frozen=True, slots=True)
class _Running:
    """The executor in use."""

    executor: Executor


@dataclass(frozen=True, slots=True)
class _Closed:
    """Final: a use raises `RuntimeError`."""


type _State = _Empty | _Running | _Closed
_EMPTY: Final = _Empty()
_CLOSED: Final = _Closed()


@final
class ExecutorBackend(Backend):
    """A backend on a `concurrent.futures` executor: created by `factory` on first use and after the last one
    broke (`BrokenExecutor`), never after `aclose` (nothing would shut it down)."""

    def __init__(self, factory: Callable[[], Executor]) -> None:
        self._factory: Final = factory
        self._state: _State = _EMPTY

    def _current(self) -> Executor:
        """The executor in use, created if there is none; `RuntimeError` once the backend is closed."""
        match self._state:
            case _Running(executor):
                return executor
            case _Empty():
                executor = self._factory()
                self._state = _Running(executor)
                return executor
            case _Closed():
                raise RuntimeError(_BACKEND_CLOSED)

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        executor = self._current()
        try:
            return await asyncio.wrap_future(executor.submit(fn, arg))
        except BrokenExecutor:
            self._drop(executor)
            raise

    def _drop(self, executor: Executor) -> None:
        """`executor` broke: the next use creates another one."""
        if isinstance(self._state, _Running) and self._state.executor is executor:
            self._state = _EMPTY
            _shut_down(executor, wait=False)

    @override
    async def aclose(self) -> None:
        state, self._state = self._state, _CLOSED
        if isinstance(state, _Running):
            await asyncio.to_thread(_shut_down, state.executor, wait=True)


def _shut_down(executor: Executor, *, wait: bool) -> None:
    """Cancels the pool tasks of `executor` not yet started and, if `wait`, waits for the running ones (blocks:
    run it in a thread then).

    An executor whose `shutdown` takes no `cancel_futures` (some of other libraries) is shut down without it, so
    one that waits waits for its queued tasks too: those of finished runs were cancelled with their callers
    already."""
    try:
        executor.shutdown(wait=wait, cancel_futures=True)
    except TypeError:
        executor.shutdown(wait=wait)


# ---- its config: creates the backend when called (on first use of its `Pools`)
@final
@dataclass(frozen=True, kw_only=True)
class FromExecutor:
    """A backend on the executors `factory` creates (e.g. an `InterpreterPoolExecutor`, or Dask's
    `client.get_executor`); for "cpu" only.

    `factory` is called on first use and again after the executor broke (`BrokenExecutor`); the backend shuts
    each executor down when its `Pools` closes (one whose `shutdown` takes no `cancel_futures` waits for its
    queued tasks). Executors that report a lost worker otherwise fail the run and stay in use. Its workers
    are not marked for worker handles: a stage `using` one opens it per input there."""

    factory: Callable[[], Executor]

    def __call__(self) -> ExecutorBackend:
        return ExecutorBackend(self.factory)
