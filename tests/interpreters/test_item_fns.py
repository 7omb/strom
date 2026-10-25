"""Tests of `strom._interpreters.item_fns`: how leaves stream their outputs and close the iterators they
open."""

import asyncio
import inspect
import threading
from collections.abc import AsyncIterator, Callable, Generator, Iterable, Iterator
from pathlib import Path
from typing import TextIO

import pytest
from helpers import WAIT_LIMIT_TIME, FailingLines, collect, outputs_of, run_error, stats_of

import strom as P


@pytest.mark.parametrize("consumer", ["async_stage", "io_stage"])
async def test_io_stage_streams_items_of_one_input(pools: P.Pools, consumer: str) -> None:
    """The iterator blocks until the next step has its first item: it streams (one pool task per item),
    and waiting in the pool does not block the event loop (an async consumer would deadlock otherwise)."""
    first_seen = threading.Event()

    def pages(n: int) -> Iterator[int]:
        yield n
        assert first_seen.wait(WAIT_LIMIT_TIME), "first item never reached the next step"
        yield n + 1

    def see(item: int) -> list[int]:
        first_seen.set()
        return [item]

    async def async_see(item: int) -> AsyncIterator[int]:
        first_seen.set()
        yield item

    seeing = P.async_stage(async_see) if consumer == "async_stage" else P.io_stage(see)
    assert sorted(await outputs_of(P.io_stage(pages) | seeing, [10], pools)) == [10, 11]


@pytest.mark.parametrize("collection", [list, tuple], ids=["list", "tuple"])
def test_io_stage_takes_one_pool_task_for_a_list_or_tuple(collection: Callable[[range], Iterable[int]]) -> None:
    """A list or tuple has nothing to stream: its items come together, one pool task per input."""

    def numbers(item: int) -> Iterable[int]:
        return collection(range(item))

    outputs, stats = stats_of(P.io_stage(numbers, concurrency=2), [5, 0, 1])
    assert sorted(outputs, key=repr) == [0, 0, 1, 2, 3, 4]
    assert stats.step("numbers").num_pool_tasks == 3


def test_io_stage_takes_one_pool_task_per_item_of_an_iterator_and_one_for_its_end() -> None:
    def numbers(item: int) -> Iterator[int]:
        yield from range(item)

    outputs, stats = stats_of(P.io_stage(numbers, concurrency=2), [5, 0, 1])
    assert sorted(outputs, key=repr) == [0, 0, 1, 2, 3, 4]
    assert stats.step("numbers").num_pool_tasks == (5 + 1) + 1 + (1 + 1)  # an empty one: found by its first task


def test_a_stage_closes_the_iterator_it_created(tmp_path: Path) -> None:
    path = tmp_path / "lines.txt"
    path.write_text("a\nb\n", encoding="utf-8")
    files: list[TextIO] = []

    def lines(_: None) -> TextIO:  # a file is its own iterator
        files.append(path.open(encoding="utf-8"))
        return files[-1]

    assert collect(P.stage(lines), [None]) == ["a\n", "b\n"]
    assert len(files) == 1
    assert files[0].closed


def test_io_stage_closes_an_iterator_whose_first_item_fails() -> None:
    closed = threading.Event()

    class FailingRows:  # an iterator that is not a generator, e.g. a DB cursor
        def __iter__(self) -> FailingRows:
            return self

        def __next__(self) -> int:
            raise ValueError("first row")

        def close(self) -> None:
            closed.set()

    with run_error(ValueError, "first row"):
        collect(P.io_stage(lambda _: FailingRows()), [None])
    assert closed.is_set()


async def test_io_stage_iterator_is_closed_after_the_item_still_being_computed() -> None:
    in_next, release = threading.Event(), threading.Event()
    gens: list[Generator[int]] = []  # keeps the generator alive: garbage collection would close it too

    def rows(_: None) -> Generator[int]:
        def blocking() -> Generator[int]:
            yield 1
            in_next.set()
            release.wait(WAIT_LIMIT_TIME)  # still running when the run is cancelled
            yield 2

        gens.append(blocking())
        return gens[-1]

    async def cancel_while_blocked(pools: P.Pools) -> None:
        run_task = asyncio.create_task(outputs_of(P.io_stage(rows), [None], pools))
        assert await asyncio.to_thread(in_next.wait, WAIT_LIMIT_TIME)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        release.set()

    async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:  # a second thread for close
        await cancel_while_blocked(pools)
    assert [inspect.getgeneratorstate(g) for g in gens] == [inspect.GEN_CLOSED]  # after `with`: close has run


@pytest.mark.parametrize(
    "make_stage",
    [
        lambda lines: P.stage(lines),  # a single event-loop step is not fused
        lambda lines: P.identity() | P.stage(lines),
        lambda lines: P.io_stage(lines),
    ],
    ids=["event loop", "fused", "io pool"],
)
def test_an_iterator_that_fails_is_closed(
    make_stage: Callable[[Callable[[int], FailingLines]], P.Stage[int, int]],
) -> None:
    iterators: list[FailingLines] = []

    def lines(_: int) -> FailingLines:
        iterators.append(FailingLines())
        return iterators[-1]

    with run_error(ValueError, "^cannot read"):
        collect(make_stage(lines), [0])
    assert len(iterators) == 1
    assert iterators[0].closed
