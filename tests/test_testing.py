"""Tests of `strom.testing`: the reference semantics, bags, the comparison with a run, the backend checks."""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import override

import pytest
from helpers import Pickling, PicklingBackend, boom, inc, many, run_error

import strom as P
from strom.backends import Backend, StreamingBackend, WorkerId
from strom.testing import (
    bag,
    check_against_reference,
    check_backend,
    check_streaming_backend,
    evaluate,
    evaluate_async,
)


def test_evaluate_gives_the_outputs_in_a_depth_first_order() -> None:
    stage = P.io_stage(many) | P.stage(inc)  # an io function, called directly
    assert evaluate(stage, [3, 0, 2]) == [1, 2, 3, 1, 2]


async def test_evaluate_async_in_a_running_loop() -> None:
    assert await evaluate_async(P.stage(inc), [1, 2]) == [2, 3]


def numbers_then_failure() -> Iterator[int]:
    yield 1
    raise KeyError("inputs failed")


def test_evaluate_fails_like_a_run() -> None:
    # ONE RunFailed of the error, noted with the stages it passed (the notes of each kind: the tests of
    # the stage notes, which run both interpreters); a fused group of event-loop steps is noted by the
    # step, not by the group's chain ('inc | boom' in a run)
    with run_error(ValueError, "boom") as info:
        evaluate(P.stage(inc) | P.stage(boom), [1])
    assert info.value.exceptions[0].__notes__ == ["in stage 'boom'"]
    with run_error(KeyError, "inputs failed") as inputs_info:  # an error of the inputs: no stage note
        evaluate(P.stage(inc), numbers_then_failure())
    assert getattr(inputs_info.value.exceptions[0], "__notes__", []) == []


def test_the_public_names_are_exactly_all() -> None:
    import strom.testing

    public = {name for name, value in vars(strom.testing).items() if not name.startswith("_")}
    public -= {name for name in public if getattr(vars(strom.testing)[name], "__module__", "") != "strom.testing"}
    assert public == set(strom.testing.__all__)


def test_bag_ignores_the_order_and_counts_repeats() -> None:
    assert bag([[1], 2, [1]]) == bag([2, [1], [1]])  # unhashable items too
    assert bag([1, 1]) != bag([1])
    assert bag([[1, 2]]) != bag([[2, 1]])  # an item counts as a whole: a list inside it keeps its order


async def test_check_against_reference_passes_for_the_same_bag(pools: P.Pools) -> None:
    await check_against_reference(P.io_stage(many, concurrency=3) | P.stage(inc), [3, 0, 2], pools)


async def late_on_0(item: int) -> AsyncIterator[int]:
    """Emits the item, item 0 only after yielding to the event loop so often (intentional) that an item taken
    after it overtakes it: a run then gives another order than the reference, which goes one by one."""
    if item == 0:
        for _ in range(20):
            await asyncio.sleep(0)
    yield item


def in_order(items: list[int]) -> list[list[int]]:
    return [sorted(items)]


async def test_a_gathered_list_is_compared_once_a_following_stage_sorted_it(pools: P.Pools) -> None:
    """The list of a `gather` comes in no particular order and is one item of the bag."""
    gathered = P.gather(P.stage(many) | P.async_stage(late_on_0, concurrency=2))
    with pytest.raises(AssertionError, match=r"missing \{'\[0, 1\]': 1\}, extra \{'\[1, 0\]': 1\}"):
        await check_against_reference(gathered, [2], pools)
    await check_against_reference(gathered | P.stage(in_order), [2], pools)


async def test_check_against_reference_names_the_items_that_differ(pools: P.Pools) -> None:
    calls = 0

    def first_call_only(item: int) -> Iterator[int]:  # the run calls it first, the reference second
        nonlocal calls
        calls += 1
        if calls == 1:
            yield item

    with pytest.raises(AssertionError, match=r"missing \{\}, extra \{'7': 1\}"):
        await check_against_reference(P.stage(first_call_only), [7], pools)


async def test_check_against_reference_raises_a_runs_error(pools: P.Pools) -> None:
    try:
        await check_against_reference(P.io_stage(boom), [1, 2], pools)
    except* ValueError as group:
        assert isinstance(group, P.RunFailed)
    else:
        raise AssertionError("the run's error did not propagate")


# ---- the contract checks of a backend
BACKENDS: dict[str, Callable[[], Backend]] = {
    "threads": P.Threads(workers=2),
    "processes": P.Processes(workers=1),
    "executor": P.FromExecutor(factory=partial(ThreadPoolExecutor, 2)),
    "pickling": Pickling(workers=2),
}
STREAMING: dict[str, Callable[[], StreamingBackend]] = {
    "threads": P.Threads(workers=2),
    "pickling": Pickling(workers=2),
}


@pytest.mark.parametrize("name", list(BACKENDS))
async def test_the_built_in_backends_keep_the_contract(name: str) -> None:
    await check_backend(BACKENDS[name])


@pytest.mark.parametrize("name", list(STREAMING))
async def test_the_streaming_backends_keep_their_contract(name: str) -> None:
    await check_streaming_backend(STREAMING[name])


class WrappingErrors(Backend):
    """Breaks the contract: the user's error arrives wrapped."""

    def __init__(self) -> None:
        self._closed = False

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A) -> B:
        if self._closed:
            raise RuntimeError("closed")
        try:
            return fn(arg)
        except Exception as error:
            raise RuntimeError("the worker failed") from error

    @override
    async def aclose(self) -> None:
        self._closed = True


class Misrouting(PicklingBackend):
    """Breaks the contract: a call with `affinity` goes to another worker than the one asked for."""

    @override
    def _executor(self, affinity: WorkerId | None) -> ThreadPoolExecutor:
        if affinity is None:
            return super()._executor(None)
        return next(executor for worker, executor in self._workers.items() if worker != affinity)


async def test_check_backend_names_a_broken_rule() -> None:
    with pytest.raises(AssertionError, match="error arrives as itself"):
        await check_backend(WrappingErrors)


async def test_check_streaming_backend_names_a_broken_rule() -> None:
    with pytest.raises(AssertionError, match="^backend contract: a call on another worker"):
        await check_streaming_backend(lambda: Misrouting(2))
