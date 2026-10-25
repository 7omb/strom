"""Tests of `strom._runtime.iterator_registry`: the iterators of `io_stage`, kept in the registry of the worker that
opened them, on the thread backend (one registry for its threads) and on `PicklingBackend` (one per worker)."""

from collections.abc import Iterator
from functools import partial
from typing import override

import pytest
from helpers import PicklingBackend

import strom as P
from strom._runtime import iterator_registry
from strom._runtime.backends import WorkerId
from strom._runtime.iterator_registry import next_item, open_iterator, release_scope
from strom.backends import StreamingBackend

SCOPE = "scope"  # the run the iterators belong to


def three_items(item: int) -> Iterator[int]:
    yield from (item, item + 1, item + 2)


def no_items(item: int) -> Iterator[int]:
    yield from ()


@pytest.mark.parametrize("name", ["threads", "pickling"])
async def test_an_iterator_is_advanced_on_the_worker_that_opened_it(name: str) -> None:
    backend: StreamingBackend = P.Threads(workers=1)() if name == "threads" else PicklingBackend(2)
    try:
        opened = await backend.run(partial(open_iterator, SCOPE, three_items), 10)
        key = opened.key
        assert key is not None
        items = [*opened.items]
        while (next_one := await backend.run(next_item, key, affinity=key.worker)) is not None:  # ty: ignore[invalid-argument-type]
            items.append(next_one.item)
        assert items == [10, 11, 12]
    finally:
        await backend.aclose()


async def test_a_call_on_another_worker_finds_no_iterator() -> None:
    backend = PicklingBackend(2)  # calls without affinity take turns: one iterator on each worker
    try:
        key = (await backend.run(partial(open_iterator, SCOPE, three_items), 10)).key
        other_key = (await backend.run(partial(open_iterator, SCOPE, three_items), 20)).key
        assert key is not None and other_key is not None
        assert key.num == other_key.num  # numbered per worker: only the worker tells them apart
        with pytest.raises(LookupError, match="misrouted"):  # not the other worker's iterator
            await backend.run(next_item, key, affinity=other_key.worker)  # ty: ignore[invalid-argument-type]
        assert await backend.run(next_item, other_key, affinity=other_key.worker) == (21,)  # ty: ignore[invalid-argument-type]
        with pytest.raises(LookupError, match="lost"):  # a worker the backend does not have (any more)
            await backend.run(next_item, key, affinity=WorkerId("gone"))
        assert backend.num_registered() == 2
        backend.release(SCOPE)  # on every worker
    finally:
        await backend.aclose()
    assert backend.num_registered() == 0


def test_an_iterator_that_ends_at_once_is_not_registered() -> None:
    assert open_iterator(SCOPE, no_items, 0) == ((), None)
    assert iterator_registry._PROCESS_REGISTRY.iterators == {}


@pytest.mark.parametrize("items", [[1, 2, 3], (1, 2, 3), [], ()], ids=["list", "tuple", "empty list", "empty tuple"])
def test_a_list_or_tuple_crosses_whole_and_is_not_registered(items: list[int] | tuple[int, ...]) -> None:
    opened = open_iterator(SCOPE, lambda _: items, None)
    assert opened.items is items  # as it is: nothing to iterate in the worker
    assert opened.key is None
    assert iterator_registry._PROCESS_REGISTRY.iterators == {}


class Lines:
    """A closable iterator that is not a generator, counting its closes."""

    def __init__(self) -> None:
        self.num_closes = 0

    def __iter__(self) -> Lines:
        return self

    def __next__(self) -> int:
        return 1

    def close(self) -> None:
        self.num_closes += 1


class FailingLines(Lines):
    @override
    def close(self) -> None:
        super().close()
        raise OSError("close failed")


def test_releasing_a_scope_closes_its_iterators_only_and_once() -> None:
    lines, other_lines = Lines(), Lines()
    key = open_iterator(SCOPE, lambda _: lines, None).key
    assert key is not None
    open_iterator("other", lambda _: other_lines, None)
    release_scope(SCOPE)
    release_scope(SCOPE)  # nothing of it is left
    assert (lines.num_closes, other_lines.num_closes) == (1, 0)
    with pytest.raises(LookupError):  # unregistered
        next_item(key)
    release_scope("other")
    assert other_lines.num_closes == 1


def test_a_release_ignores_the_errors_of_the_closes() -> None:
    failing, lines = FailingLines(), Lines()
    open_iterator(SCOPE, lambda _: failing, None)
    open_iterator(SCOPE, lambda _: lines, None)
    release_scope(SCOPE)  # raises nothing, and closes the next one too
    assert (failing.num_closes, lines.num_closes) == (1, 1)
