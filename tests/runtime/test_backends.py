"""Tests of `strom._runtime.backends`: the contract of `strom.backends.Backend`, checked on every built-in
backend (what they do beyond it: `test_executor_backend.py`, `test_thread_backend.py`, `test_process_backend.py`)
and on `PicklingBackend`, a test-only backend without shared memory that behaves like a remote one.

The functions run on the backends are top-level (picklable) and talk to the test through module-level
state: the workers of all backends here except the process backend are threads of this process."""

import asyncio
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from helpers import WAIT_LIMIT_TIME, Pickling, inc

import strom as P
from strom._runtime.iterator_registry import open_iterator
from strom.backends import Backend, StreamingBackend

BACKENDS: dict[str, Callable[[], Backend]] = {
    "threads": P.Threads(workers=1),
    "processes": P.Processes(workers=1),
    "executor": P.FromExecutor(factory=partial(ThreadPoolExecutor, 1)),
    "pickling": Pickling(workers=1),
}
IN_PROCESS = ["threads", "executor", "pickling"]  # their workers can signal the test through module state
STREAMING: dict[str, Callable[[], StreamingBackend]] = {
    "threads": P.Threads(workers=1),
    "pickling": Pickling(workers=1),
}

HELD, RELEASED = threading.Event(), threading.Event()
RAN: list[str] = []


@pytest.fixture(autouse=True)
def _reset() -> None:
    HELD.clear()
    RELEASED.clear()
    RAN.clear()


def held(name: str) -> str:
    """Signals that it runs, then waits for the test to release it."""
    RAN.append(name)
    HELD.set()
    assert RELEASED.wait(WAIT_LIMIT_TIME)
    return name


def ran(name: str) -> str:
    RAN.append(name)
    return name


class Noted(Exception):
    pass


def fail_with_a_note(item: int) -> int:
    error = Noted(f"failed on {item}")
    error.add_note("noted in the worker")
    raise error


async def wait_until_held() -> None:
    assert await asyncio.to_thread(HELD.wait, WAIT_LIMIT_TIME)


@pytest.mark.parametrize("name", list(BACKENDS))
async def test_runs_a_function_on_its_argument(name: str) -> None:
    backend = BACKENDS[name]()
    try:
        assert await backend.run(inc, 1) == [2]
    finally:
        await backend.aclose()


@pytest.mark.parametrize("name", list(BACKENDS))
async def test_raises_the_users_error_as_itself(name: str) -> None:
    backend = BACKENDS[name]()
    try:
        with pytest.raises(Noted, match=r"^failed on 3") as info:
            await backend.run(fail_with_a_note, 3)
        assert info.value.__notes__ == ["noted in the worker"]
    finally:
        await backend.aclose()


@pytest.mark.parametrize("name", IN_PROCESS)
async def test_a_cancelled_pool_task_that_has_not_started_never_runs(name: str) -> None:
    backend = BACKENDS[name]()  # one worker: the second task waits behind the first
    try:
        first_task = asyncio.create_task(backend.run(held, "first"))
        await wait_until_held()
        second_task = asyncio.create_task(backend.run(ran, "second"))
        await asyncio.sleep(0)  # intentional: the second task submits its pool task
        second_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await second_task
        RELEASED.set()
        assert await first_task == "first"
    finally:
        RELEASED.set()
        await backend.aclose()
    assert RAN == ["first"]


class Rows:
    """An endless closable iterator that is not a generator (only an explicit `close()` closes it), logging
    its close to `RAN`."""

    def __init__(self, name: str) -> None:
        self.name = name

    def __iter__(self) -> Rows:
        return self

    def __next__(self) -> str:
        return self.name

    def close(self) -> None:
        RAN.append(f"closed {self.name}")


def rows(name: str) -> Rows:
    return Rows(name)


def held_rows(name: str) -> Rows:
    return Rows(held(name))


@pytest.mark.parametrize("name", list(STREAMING))
async def test_a_release_closes_the_iterators_of_its_scope_only(name: str) -> None:
    backend = STREAMING[name]()  # one worker: a call after the release runs after it
    scope, other_scope = uuid.uuid4().hex, uuid.uuid4().hex
    try:
        await backend.run(partial(open_iterator, scope, rows), "a")
        await backend.run(partial(open_iterator, other_scope, rows), "b")
        backend.release(scope)
        await backend.run(ran, "after")
        assert RAN == ["closed a", "after"]
        backend.release(other_scope)
    finally:
        await backend.aclose()
    assert RAN == ["closed a", "after", "closed b"]


@pytest.mark.parametrize("name", list(STREAMING))
async def test_a_release_waits_for_a_running_task_whose_caller_left(name: str) -> None:
    # The run's end releases its scope while a pool task of a cancelled caller still opens an iterator of it:
    # the release must close that iterator too, so it runs after the task.
    backend = STREAMING[name]()
    scope = uuid.uuid4().hex
    try:
        task = asyncio.create_task(backend.run(partial(open_iterator, scope, held_rows), "a"))
        await wait_until_held()
        task.cancel()  # abandons the running pool task: it finishes, and registers the iterator
        with pytest.raises(asyncio.CancelledError):
            await task
        backend.release(scope)
        RELEASED.set()
    finally:
        RELEASED.set()
        await backend.aclose()
    assert RAN == ["a", "closed a"]


def threads_of(item: int) -> Iterator[tuple[int, int]]:
    """Five times the input with the thread that produced the item."""
    for _ in range(5):
        time.sleep(0.001)  # intentional: the pool tasks of other inputs take the threads in between
        yield item, threading.get_ident()


@pytest.mark.parametrize("name", list(STREAMING))
async def test_all_items_of_an_input_come_from_the_thread_that_opened_its_iterator(name: str) -> None:
    """Affinity is real on every streaming backend: more iterators open at once than there are threads."""
    io: Callable[[], StreamingBackend] = P.Threads(workers=3) if name == "threads" else Pickling(workers=3)
    threads: dict[int, set[int]] = {}
    async with (
        P.Pools.open_on(cpu=P.Threads(workers=1), io=io) as pools,
        P.stream(P.io_stage(threads_of, concurrency=4), range(12), pools) as outputs,
    ):
        async for item, thread in outputs:
            threads.setdefault(item, set()).add(thread)
    assert sorted(threads) == list(range(12))
    assert all(len(of_input) == 1 for of_input in threads.values())
    assert len(set().union(*threads.values())) == 3  # every thread took part


@pytest.mark.parametrize("name", list(BACKENDS))
async def test_a_closed_backend_cannot_be_used(name: str) -> None:
    backend = BACKENDS[name]()
    assert await backend.run(inc, 1) == [2]
    await backend.aclose()
    with pytest.raises(RuntimeError):  # never a new executor that nothing would shut down
        await backend.run(inc, 1)


@pytest.mark.parametrize("name", list(STREAMING))
async def test_a_closed_streaming_backend_releases_nothing(name: str) -> None:
    backend = STREAMING[name]()
    await backend.aclose()
    with pytest.raises(RuntimeError):
        backend.release(uuid.uuid4().hex)


@pytest.mark.parametrize("name", list(BACKENDS))
async def test_closing_a_handle_no_worker_holds_returns(name: str) -> None:
    """`close_handle` of a key that no worker opened (here: none ever did) waits for nothing and raises nothing,
    before and after the workers exist. (Closing held handles: `test_worker_handle.py`,
    `test_process_backend.py`.)"""
    backend = BACKENDS[name]()
    try:
        await backend.close_handle(uuid.uuid4().hex)
        assert await backend.run(inc, 1) == [2]
        await asyncio.wait_for(backend.close_handle(uuid.uuid4().hex), WAIT_LIMIT_TIME)
    finally:
        await backend.aclose()


@pytest.mark.parametrize("name", IN_PROCESS)
async def test_closing_does_not_block_the_event_loop(name: str) -> None:
    """A pool task still running makes closing wait for it; meanwhile the event loop runs other tasks."""
    num_beats = 0

    async def heartbeat() -> None:
        nonlocal num_beats
        while True:
            num_beats += 1
            await asyncio.sleep(0)

    backend = BACKENDS[name]()
    task = asyncio.create_task(backend.run(held, "busy"))
    await wait_until_held()
    beat_task = asyncio.create_task(heartbeat())
    asyncio.get_running_loop().call_later(0.05, RELEASED.set)  # intentional: the close must have begun by then
    await backend.aclose()
    beat_task.cancel()
    assert await task == "busy"
    assert num_beats > 10
