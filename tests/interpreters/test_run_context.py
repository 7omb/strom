"""Tests of `strom._interpreters.run_context`: `start_tasks`, as far as no run shows it (`test_streaming.py` tests
the task groups, the stage notes and the ends of streams of every stage kind through runs)."""

import asyncio

import pytest

from strom._interpreters.run_context import RunState, start_tasks


async def test_the_check_after_the_tasks_counts_as_an_error_of_theirs() -> None:
    """What a join passes to check that every input is complete (in a run it never fails): it runs once the
    tasks have ended; its error is noted with the stage, and the output stream ends all the same."""
    outq: asyncio.Queue[int] = asyncio.Queue()
    order: list[str] = []

    async def put_one() -> None:
        outq.put_nowait(1)
        order.append("the task ended")

    def start(inner_tg: asyncio.TaskGroup) -> None:
        inner_tg.create_task(put_one())

    def check() -> None:
        order.append("checked")
        raise AssertionError("an input is not complete")

    with pytest.RaisesGroup(pytest.RaisesExc(AssertionError, match="^an input is not complete")) as caught:
        async with asyncio.TaskGroup() as tg:
            start_tasks(tg, outq, start, RunState(), name="pairs", ended=check)
    assert order == ["the task ended", "checked"]
    assert caught.value.exceptions[0].__notes__ == ["in stage 'pairs'"]
    assert outq.get_nowait() == 1
    with pytest.raises(asyncio.QueueShutDown):  # the end of the stream
        outq.get_nowait()
