"""Tests of `strom._runtime.thread_backend`: what `ThreadBackend` and `Threads` do beyond the contract of every
backend (`test_backends.py`): its threads' names and registries, where calls without affinity go while a thread
holds an iterator, and the check that every iterator was released."""

import threading
import time
import uuid
from functools import partial

import pytest
from helpers import WAIT_LIMIT_TIME

import strom as P
from strom._runtime.iterator_registry import next_item, open_iterator
from strom._runtime.thread_backend import ThreadBackend


class Rows:
    """An endless closable iterator that is not a generator: only an explicit `close()` closes it."""

    def __init__(self) -> None:
        self.closed_in: list[str] = []

    def __iter__(self) -> Rows:
        return self

    def __next__(self) -> str:
        return threading.current_thread().name

    def close(self) -> None:
        self.closed_in.append(threading.current_thread().name)


def thread_name(_: None) -> str:
    return threading.current_thread().name


def wait_until_idle(backend: ThreadBackend) -> None:
    """Returns once every thread of the backend waits for a call (a thread goes idle a moment after the result
    of its call is out). Polls every half millisecond (intentional: the pool has no signal for it)."""
    pool = backend._pool
    deadline = time.monotonic() + WAIT_LIMIT_TIME
    while len(pool._idle_free) + len(pool._idle_holding) != len(pool._threads):
        assert time.monotonic() < deadline, "the threads did not go idle"
        time.sleep(0.0005)


async def test_an_iterator_stays_on_its_thread_and_other_calls_go_to_the_other_threads() -> None:
    backend = P.Threads(workers=2, name="rows")()
    rows = Rows()
    scope = uuid.uuid4().hex
    try:
        opened = await backend.run(partial(open_iterator, scope, lambda _: rows), None)
        key = opened.key
        assert key is not None and opened.items == ("rows_0",)
        for _ in range(5):  # the holder is idle, yet a call without affinity goes to the other thread
            wait_until_idle(backend)
            assert await backend.run(thread_name, None) == "rows_1"
            next_one = await backend.run(next_item, key, affinity=key.worker)  # ty: ignore[invalid-argument-type]
            assert next_one is not None and next_one.item == "rows_0"
        backend.release(scope)
    finally:
        await backend.aclose()
    assert rows.closed_in == ["rows_0"]  # released on the thread that opened it


async def test_an_iterator_that_was_never_released_fails_the_close_and_is_closed() -> None:
    backend = P.Threads(workers=1, name="rows")()
    rows = Rows()
    await backend.run(partial(open_iterator, uuid.uuid4().hex, lambda _: rows), None)
    with pytest.raises(AssertionError, match="1 io_stage iterators were not released"):
        await backend.aclose()  # no run forgets its release: a bug of the library, shown where it is cheap
    assert rows.closed_in == ["rows_0"]
