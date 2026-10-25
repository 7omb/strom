"""Tests of `strom._interpreters.reference`: the reference semantics (`run_reference`, `testing.evaluate`)."""

import asyncio
from collections.abc import AsyncGenerator, Iterator

import pytest
from helpers import boom, inc, many, meaning, neg, run_error

import strom as P
from strom._interpreters.reference import _focusing, run_reference
from strom._stages.focus import Focus, counting_focus, first_focus, second_focus


def test_meaning_of_a_stage_as_a_plain_function() -> None:
    stage = P.io_stage(many) | P.duplicate() | P.product(P.stage(neg), P.cpu_stage(inc))
    assert meaning(stage, [2, 3]) == [(0, 1), (-1, 2), (0, 1), (-1, 2), (-2, 3)]
    assert meaning(P.io_stage(many), [0]) == []  # an input without outputs


def numbers_then_failure(_: None) -> Iterator[int]:
    yield from range(1000)
    raise KeyError("inputs failed")


def test_meaning_evaluates_depth_first() -> None:
    # Each output passes the rest of the chain before the next one is produced, so `boom` (on item 2)
    # fails before the stage's function does, as in a run.
    with run_error(ValueError, "boom"):
        meaning(P.stage(numbers_then_failure) | P.stage(boom), [None])


def test_reference_loop_closes_the_open_outputs_when_stopped_early() -> None:
    # Checked inside the running loop: unclosed async generators are closed later, at the loop's shutdown.
    closed: list[int] = []

    def endless_countdown(item: int) -> Iterator[P.Left[int] | P.Right[int]]:
        try:
            yield P.Right(item)
            yield P.Left(item + 1)
        finally:
            closed.append(item)

    async def check() -> None:
        outs = run_reference(P.loop(P.stage(endless_countdown)))(0)
        assert [await anext(outs) for _ in range(3)] == [0, 1, 2]  # three body outputs open
        await outs.aclose()
        assert closed == [2, 1, 0]  # the newest first

    asyncio.run(check())


@pytest.mark.parametrize(
    "focus",
    [first_focus(), second_focus(), counting_focus(lambda _, __: None)],
    ids=["first", "second", "counting"],
)
def test_focusing_closes_the_inner_outputs_when_stopped_early(
    focus: Focus[tuple[int, int], object, int, int, int],
) -> None:
    # Checked right after `aclose()` returns: otherwise the event loop's finalizer hook would close an
    # unreferenced inner generator a little later and hide a missing close.
    closed: list[int] = []

    async def endless(item: int) -> AsyncGenerator[int]:
        try:
            while True:
                yield item
        finally:
            closed.append(item)

    async def stop_early() -> list[int]:
        outs = _focusing(focus, endless)((1, 1))
        await anext(outs)
        await outs.aclose()
        return list(closed)  # a copy: the loop's shutdown would close the inner generator later

    assert asyncio.run(stop_early()) == [1]
