"""Tests of `strom._runtime.executor_backend`: what `ExecutorBackend` and `FromExecutor` do beyond the contract of
every backend (`test_backends.py`): the lifetime of the user's executor (created on first use, replaced when
broken, never after the close) and its shutdown."""

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.thread import BrokenThreadPool
from typing import override

import pytest
from helpers import inc

import strom as P


class NoCancelFuturesExecutor(ThreadPoolExecutor):
    """An executor whose `shutdown` rejects `cancel_futures`, as one of another library without the parameter
    does (`TypeError`)."""

    @override
    def shutdown(self, wait: bool = True, *, cancel_futures: bool = False) -> None:
        if cancel_futures:
            raise TypeError("shutdown() got an unexpected keyword argument 'cancel_futures'")
        super().shutdown(wait=wait)


async def test_an_executor_without_cancel_futures_is_shut_down() -> None:
    executors: list[NoCancelFuturesExecutor] = []

    def factory() -> NoCancelFuturesExecutor:
        executors.append(NoCancelFuturesExecutor(1))
        return executors[-1]

    backend = P.FromExecutor(factory=factory)()
    assert await backend.run(inc, 1) == [2]
    await backend.aclose()  # was: TypeError from `shutdown(cancel_futures=True)`
    assert executors[0]._shutdown


def failing_initializer() -> None:
    raise RuntimeError("worker setup failed")  # breaks the pool (`BrokenThreadPool`)


async def test_a_broken_executor_is_dropped_and_replaced() -> None:
    executors: list[ThreadPoolExecutor] = []

    def factory() -> ThreadPoolExecutor:
        executors.append(ThreadPoolExecutor(1, initializer=failing_initializer if not executors else None))
        return executors[-1]

    backend = P.FromExecutor(factory=factory)()
    with pytest.raises(BrokenThreadPool):
        await backend.run(inc, 1)
    assert executors[0]._shutdown
    assert await backend.run(inc, 1) == [2]  # on a new executor
    assert len(executors) == 2
    await backend.aclose()
    assert executors[1]._shutdown


async def test_an_executor_is_created_on_first_use_and_never_after_the_close() -> None:
    created: list[ThreadPoolExecutor] = []

    def factory() -> ThreadPoolExecutor:
        created.append(ThreadPoolExecutor(1))
        return created[-1]

    backend = P.FromExecutor(factory=factory)()
    await backend.aclose()  # never used: nothing to shut down
    with pytest.raises(RuntimeError, match="closed"):
        await backend.run(inc, 1)
    assert not created
