"""Pools: one backend per resource, shared by the steps of one or more runs."""

import asyncio
import os
import sys
import warnings
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Final, Literal, Self, final

from strom._runtime.backends import Backend, StreamingBackend
from strom._runtime.process_backend import Processes
from strom._runtime.thread_backend import Threads
from strom._validation import check_positive

type CpuBackendKind = Literal["process", "thread"]
"""The built-in backend `Pools.open` creates for the "cpu" pool (see "Backends" in the package docstring)."""


def default_cpu_workers() -> int:
    """Hardware size: CPUs usable by this process."""
    return os.process_cpu_count() or 1


def default_io_workers() -> int:
    """Same formula as ThreadPoolExecutor's own default."""
    return min(32, default_cpu_workers() + 4)


def _gil_enabled() -> bool:
    return sys._is_gil_enabled()  # pyright: ignore[reportPrivateUsage]  # no public equivalent


@dataclass(frozen=True, kw_only=True)
class PoolConfig:
    """The backend config of each resource, which creates its backend on first use: e.g. `Processes(workers=8)`,
    `Threads(workers=16)`.

    Any callable returning a backend is a backend config; "io" needs a `StreamingBackend` (`io_stage` streams
    iterators)."""

    cpu: Callable[[], Backend]
    io: Callable[[], StreamingBackend]


@final
@dataclass(frozen=True, slots=True)
class RunBackends:
    """What a run needs of its `Pools` (`backends_of`): the backend of each resource, resolved on each use
    (created on the first; `RuntimeError` once the pools are closed), and the release of a run's scope on the
    "io" backend (`StreamingBackend.release`; nothing if it was never created or the pools are closed)."""

    cpu: Callable[[], Backend]
    io: Callable[[], StreamingBackend]
    release: Callable[[str], None]


_POOLS_CLOSED = "Pools is closed; create a new one"


class Pools:
    """One backend per resource, created lazily from `config`; only inside `async with Pools.open(...)` (or
    `Pools.open_on(...)`).

    Reusable across runs until the block ends; a closed `Pools` raises `RuntimeError` on any further
    use. Use a `Pools` within one event loop (several concurrent runs in it are fine); backends may
    otherwise be created twice and leak.

    async with Pools.open(cpu_workers=8, io_workers=16) as pools:
        async with stream(PIPELINE_A, inputs, pools) as outputs: ...
        async with stream(PIPELINE_B, inputs, pools) as outputs: ...  # same pool workers, no second startup
    """

    def __init__(self, config: PoolConfig, opening: object = None) -> None:
        if opening is not _OPENING:  # only `_opened` constructs one: a `Pools` outside its block is never closed
            raise TypeError("a Pools exists only inside `async with Pools.open(...)` or `Pools.open_on(...)`")
        self.config: Final = config  # fixed: the backends are created from it
        self._cpu: Backend | None = None
        self._io: StreamingBackend | None = None
        self._closed = False
        self._run_backends: Final = RunBackends(cpu=self._cpu_backend, io=self._io_backend, release=self._release)

    @classmethod
    def open(
        cls,
        *,
        cpu_workers: int | None = None,
        io_workers: int | None = None,
        cpu_backend: CpuBackendKind = "process",
    ) -> AbstractAsyncContextManager[Self]:
        """The pools for the `async with` block: `cpu_workers` processes (or threads) and `io_workers` threads;
        by default `default_cpu_workers()` and `default_io_workers()`.

        Short for `Pools.open_on(cpu=Processes(...) or Threads(...), io=Threads(...))`. At the end of the
        block, pool tasks not yet started are cancelled and running ones are waited for, in a thread: the
        event loop goes on meanwhile, and a cancelled exit still closes them. The configuration is checked
        here, at the call (its warning names the caller's line)."""
        cpu_workers = default_cpu_workers() if cpu_workers is None else cpu_workers
        io_workers = default_io_workers() if io_workers is None else io_workers
        check_positive("cpu_workers", cpu_workers)
        check_positive("io_workers", io_workers)
        if cpu_backend == "thread":
            if _gil_enabled():  # reported at the caller of `open`
                warnings.warn(
                    "cpu_backend='thread' with the GIL enabled gives no CPU parallelism; use python3.14t",
                    RuntimeWarning,
                    stacklevel=2,
                )
            cpu: Callable[[], Backend] = Threads(workers=cpu_workers, name="cpu")
        else:
            cpu = Processes(workers=cpu_workers)
        return _opened(cls, PoolConfig(cpu=cpu, io=Threads(workers=io_workers, name="io")))

    @classmethod
    def open_on(
        cls, *, cpu: Callable[[], Backend], io: Callable[[], StreamingBackend]
    ) -> AbstractAsyncContextManager[Self]:
        """The pools for the `async with` block, on the given backends: e.g.
        `Pools.open_on(cpu=Processes(workers=8), io=Threads(workers=16))`; closing as for `Pools.open`."""
        return _opened(cls, PoolConfig(cpu=cpu, io=io))

    @property
    def closed(self) -> bool:
        """True after the `async with` block of `Pools.open` or `Pools.open_on`; a closed `Pools` can't be used."""
        return self._closed

    def _cpu_backend(self) -> Backend:
        check_open(self)
        if self._cpu is None:
            self._cpu = self.config.cpu()
        return self._cpu

    def _io_backend(self) -> StreamingBackend:
        check_open(self)
        if self._io is None:
            self._io = self.config.io()
        return self._io

    def _release(self, scope: str) -> None:
        if self._io is not None:  # None also once closed: a run outliving its pools has no backend left
            self._io.release(scope)

    async def _aclose(self) -> None:
        """Final: no later use. Closes the backends, concurrently.

        Shielded: a cancelled caller stops waiting, the backends still close (`asyncio.run` waits for the
        threads they close in). An error of one backend's close does not stop the others."""
        self._closed = True
        backends = created_backends(self)
        self._cpu = self._io = None
        if backends:
            await asyncio.shield(_close_all(backends))


def check_open(pools: Pools) -> None:
    """Raises `RuntimeError` if `pools` is closed (any use after its block, also by a run)."""
    if pools.closed:
        raise RuntimeError(_POOLS_CLOSED)


def backends_of(pools: Pools) -> RunBackends:
    """What a run needs of `pools`: its backends, created on first use; `RuntimeError` once it is closed."""
    return pools._run_backends  # pyright: ignore[reportPrivateUsage]  # `Pools`' own module


def created_backends(pools: Pools) -> list[Backend]:
    """The backends of `pools` created so far (none once it is closed): those whose workers may hold handles."""
    return [backend for backend in (pools._cpu, pools._io) if backend is not None]  # pyright: ignore[reportPrivateUsage]  # `Pools`' own module


async def _close_all(backends: list[Backend]) -> None:
    results = await asyncio.gather(*(backend.aclose() for backend in backends), return_exceptions=True)
    errors = [result for result in results if result is not None]
    if errors:
        raise BaseExceptionGroup("closing the pools failed", errors)


_OPENING: Final = object()  # passed by `_opened` only (see `Pools.__init__`)


@asynccontextmanager
async def _opened[P: Pools](pools_class: type[P], config: PoolConfig) -> AsyncGenerator[P]:
    pools = pools_class(config, _OPENING)
    try:
        yield pools
    finally:
        await pools._aclose()  # pyright: ignore[reportPrivateUsage]  # `Pools.open`'s own generator
