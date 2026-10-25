"""Tests of `strom._runners`: the runner `stream`: outputs, the body's scope (errors, cancellation,
stopping early), the inputs (sync and async) and the release of the run's scope."""

import asyncio
import inspect
import itertools
import threading
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Callable, Generator, Iterable, Iterator
from typing import override

import pytest
from helpers import (
    SATURATION_GRACE_TIME,
    WAIT_LIMIT_TIME,
    CountingThreads,
    Failure,
    PicklingBackend,
    fail_on_7,
    inc,
    outputs_of,
    run_error,
)

import strom as P


# ------------------------------------------------------------------------------ outputs
async def test_concurrent_runs_in_one_event_loop(pools: P.Pools) -> None:
    failing = threading.Event()

    def fail_on_two(item: int) -> list[int]:
        if item == 2:
            failing.set()
            raise ValueError("boom")
        return [item]

    def continue_after_failure_started(item: int) -> list[int]:  # the good run is still going while the other fails
        assert failing.wait(WAIT_LIMIT_TIME)
        return [item]

    good, failed = await asyncio.gather(
        outputs_of(P.io_stage(continue_after_failure_started, concurrency=2), range(30), pools),
        outputs_of(P.io_stage(fail_on_two, concurrency=2), range(30), pools),
        return_exceptions=True,
    )
    assert isinstance(good, list)
    assert sorted(good) == list(range(30))
    assert isinstance(failed, BaseExceptionGroup)
    assert run_error(ValueError, "^boom").matches(failed)


async def test_outputs_come_as_they_are_made(pools: P.Pools) -> None:
    first_seen = threading.Event()

    def two_pages(_: None) -> Iterator[int]:
        yield 1
        assert first_seen.wait(WAIT_LIMIT_TIME), "the consumer never got the first output"
        yield 2

    async with P.stream(P.io_stage(two_pages), [None], pools) as outputs:
        seen = []
        async for out in outputs:
            seen.append(out)
            first_seen.set()
    assert seen == [1, 2]


async def test_consumers_in_a_task_group_share_the_outputs(pools: P.Pools) -> None:
    taken: list[list[int]] = [[], [], []]

    async def consume(outputs: AsyncIterator[int], mine: list[int]) -> None:
        async for out in outputs:
            mine.append(out)
            await asyncio.sleep(0)  # lets the other consumers take outputs too

    async with P.stream(P.stage(inc), range(60), pools) as outputs, asyncio.TaskGroup() as tg:
        for mine in taken:
            tg.create_task(consume(outputs, mine))
    assert sorted(out for mine in taken for out in mine) == list(range(1, 61))  # each output to one consumer
    assert all(taken)


async def test_a_slow_consumer_holds_the_run_back(pools: P.Pools) -> None:
    """Backpressure from the consumer: while it holds an output, the run takes only as many inputs as its
    queues hold."""
    taken = num_taken = 0

    def numbers() -> Iterator[int]:
        nonlocal taken
        for item in itertools.count():
            taken += 1
            yield item

    async with P.stream(P.stage(inc), numbers(), pools) as outputs:
        async for _ in outputs:
            await asyncio.sleep(SATURATION_GRACE_TIME)  # intentional: time to take more inputs, if it would
            num_taken = taken
            break
    # the output held, the step's output queue, the item the step waits to put, the queue of the inputs,
    # the item the feeder waits to put
    assert num_taken == 1 + 10 + 1 + 10 + 1


# --------------------------------------------------------- the body's scope (as a task group)
async def test_stopping_early_cancels_the_run_without_an_error(pools: P.Pools) -> None:
    gens: list[Generator[int]] = []

    def endless(item: int) -> Generator[int]:
        def numbers() -> Generator[int]:
            while True:
                yield item

        gens.append(numbers())
        return gens[-1]

    async with asyncio.timeout(WAIT_LIMIT_TIME):  # a run not cancelled at the end of the block would never end
        async with P.stream(P.stage(endless), itertools.count(), pools) as outputs:
            async for _ in outputs:
                break
    assert [inspect.getgeneratorstate(gen) for gen in gens] == [inspect.GEN_CLOSED]  # in the loop: references kept


async def test_a_run_failure_cancels_the_body(pools: P.Pools) -> None:
    waited_to_the_end = False

    async with asyncio.timeout(WAIT_LIMIT_TIME):  # the body would wait that long if it was not cancelled
        with run_error(Failure, "in stage 'fail_on_7'"):
            async with P.stream(P.io_stage(fail_on_7), range(10), pools) as outputs:
                async for out in outputs:
                    if out == 0:
                        await asyncio.Event().wait()  # an await of the body's own, not of the outputs
                        waited_to_the_end = True
    assert not waited_to_the_end


@pytest.mark.parametrize("depth", [1, 3, 6])
async def test_a_run_failure_cancels_a_consumer_nested_in_task_groups(pools: P.Pools, depth: int) -> None:
    """The block's cancellation reaches a consumer one loop iteration per task group around it: however deep,
    the consumer is cancelled and raises nothing of its own beside the run's error."""
    seen: list[type[BaseException]] = []

    async def consume(outputs: AsyncIterator[int], depth: int) -> None:
        if depth > 0:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(consume(outputs, depth - 1))
            return
        try:
            async for _ in outputs:
                pass
        except BaseException as error:
            seen.append(type(error))
            raise

    async with asyncio.timeout(WAIT_LIMIT_TIME):
        with run_error(Failure, "in stage 'fail_on_7'"):  # exactly one error: the run's
            async with P.stream(P.io_stage(fail_on_7), [7], pools) as outputs:
                await consume(outputs, depth)
    assert seen == [asyncio.CancelledError]


async def test_a_run_failure_does_not_look_like_the_end_of_the_stream(pools: P.Pools) -> None:
    """The steps end their output queue also when they fail: the code after the loop must not run."""
    after_the_loop = False
    with run_error(Failure):
        async with P.stream(P.io_stage(fail_on_7), [7], pools) as outputs:
            async for _ in outputs:
                pass
            after_the_loop = True
    assert not after_the_loop


async def test_a_body_error_comes_out_in_the_runs_group(pools: P.Pools) -> None:
    with run_error(KeyError, "^'body'$") as caught:
        async with P.stream(P.stage(inc), range(10), pools) as outputs:
            async for _ in outputs:
                raise KeyError("body")
    assert not hasattr(caught.value.exceptions[0], "__notes__")  # it passed no stage


async def test_a_users_exception_group_from_the_body_stays_whole(pools: P.Pools) -> None:
    users = ExceptionGroup("the user's group", [KeyError("a"), KeyError("b")])
    with pytest.raises(ExceptionGroup) as info:
        async with P.stream(P.stage(inc), range(10), pools) as outputs:
            async for _ in outputs:
                raise users
    assert info.value.exceptions == (users,)


async def test_body_and_run_errors_come_out_together(pools: P.Pools) -> None:
    """The body raises after the run failed, before the run's failure reached it."""
    about_to_fail = asyncio.Event()

    async def fail(item: int) -> AsyncIterator[int]:
        about_to_fail.set()
        raise Failure(item)
        yield item  # an async generator

    with pytest.raises(ExceptionGroup) as info:
        async with P.stream(P.async_stage(fail), [1], pools):
            await about_to_fail.wait()  # resumes before the run task has ended
            raise KeyError("body")
    assert sorted(type(error).__name__ for error in info.value.exceptions) == ["Failure", "KeyError"]


async def test_outputs_used_after_the_block_raise(pools: P.Pools) -> None:
    async with P.stream(P.stage(inc), range(3), pools) as outputs:
        pass
    with pytest.raises(RuntimeError, match="stream is closed"):
        await anext(outputs)


async def test_a_consumer_outside_the_block_gets_an_error_not_a_hang(pools: P.Pools) -> None:
    """A task outside the block's scope is not cancelled by the run's failure: it must not wait forever."""

    async def consume(outputs: AsyncIterator[int]) -> None:
        async for _ in outputs:
            pass

    outside: list[asyncio.Task[None]] = []
    with run_error(Failure):
        async with P.stream(P.io_stage(fail_on_7), [7], pools) as outputs:
            outside.append(asyncio.get_running_loop().create_task(consume(outputs)))  # not in the block's scope
            await asyncio.Event().wait()  # cancelled by the run's failure
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        with pytest.raises(RuntimeError, match="the run failed"):
            await outside[0]


async def test_a_consumer_outside_the_block_gets_its_error_once_the_block_has_ended(pools: P.Pools) -> None:
    """Until the block has ended, a waiting consumer cannot tell whether the block's cancellation is still on
    its way to it: here the body takes some loop iterations to end (a cleanup)."""
    order: list[str] = []

    async def consume(outputs: AsyncIterator[int]) -> None:
        try:
            async for _ in outputs:
                pass
        finally:
            order.append("the consumer got its error")

    outside: list[asyncio.Task[None]] = []
    with run_error(Failure):
        async with P.stream(P.io_stage(fail_on_7), [7], pools) as outputs:
            outside.append(asyncio.get_running_loop().create_task(consume(outputs)))  # not in the block's scope
            try:
                await asyncio.Event().wait()  # cancelled by the run's failure
            finally:
                for _ in range(10):
                    await asyncio.sleep(0)  # intentional: the consumer runs meanwhile and finds the run failed
                order.append("the body ended")
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        with pytest.raises(RuntimeError, match="the run failed"):
            await outside[0]
    assert order == ["the body ended", "the consumer got its error"]


async def test_cancelling_a_run_from_outside_raises_cancelled(pools: P.Pools) -> None:
    running = asyncio.Event()  # the run is going: its first output was taken

    async def consume() -> None:
        async with P.stream(P.stage(inc), itertools.count(), pools) as outputs:
            async for _ in outputs:
                running.set()
                await asyncio.sleep(0)

    task = asyncio.create_task(consume())
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        await running.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ------------------------------------------------------------------------------- inputs
async def test_async_inputs(pools: P.Pools) -> None:
    async def numbers() -> AsyncIterator[int]:
        for item in range(5):
            await asyncio.sleep(0)  # an async producer waits between its items
            yield item

    assert sorted(await outputs_of(P.io_stage(inc, concurrency=2), numbers(), pools)) == [1, 2, 3, 4, 5]


async def test_an_object_iterable_both_ways_is_iterated_async(pools: P.Pools) -> None:
    class Both:
        def __iter__(self) -> Iterator[int]:
            return iter([1])

        def __aiter__(self) -> AsyncIterator[int]:
            async def items() -> AsyncIterator[int]:
                yield 2

            return items()

    assert await outputs_of(P.stage(inc), Both(), pools) == [3]


def failing_lines() -> Generator[int]:
    yield 1
    raise ValueError("cannot read")


async def async_failing_lines() -> AsyncGenerator[int]:
    yield 1
    raise ValueError("cannot read")


@pytest.mark.parametrize("make_inputs", [failing_lines, async_failing_lines], ids=["sync", "async"])
async def test_an_error_of_the_inputs_ends_the_run_without_a_stage_note(
    pools: P.Pools, make_inputs: Callable[[], Iterable[int] | AsyncIterable[int]]
) -> None:
    with run_error(ValueError, "^cannot read$") as caught:
        await outputs_of(P.io_stage(inc), make_inputs(), pools)
    assert not hasattr(caught.value.exceptions[0], "__notes__")  # it passed no stage


async def test_an_exception_group_of_the_inputs_stays_whole(pools: P.Pools) -> None:
    users = ExceptionGroup("the user's group", [KeyError("a"), KeyError("b")])

    def numbers() -> Iterator[int]:
        yield 1
        raise users

    with pytest.raises(ExceptionGroup) as info:
        await outputs_of(P.io_stage(inc), numbers(), pools)
    assert info.value.exceptions == (users,)


async def test_queued_pool_tasks_do_not_run_after_an_error_of_the_inputs() -> None:
    """Cancelling the steps cancels their queued pool tasks; the failure flag the inputs set as well only
    narrows the window before that (removing it passes: the window is too short to hit)."""
    io_pool = CountingThreads(workers=1)
    failed = threading.Event()  # set by the inputs just before they fail
    started: list[int] = []

    def numbers() -> Iterator[int]:
        """Fails once all four tasks of the step have submitted a pool task (three wait behind the first)."""
        for item in itertools.count():
            if io_pool.num_submitted >= 4:
                failed.set()
                raise ValueError("cannot read")
            yield item

    def wait_for_the_failure(item: int) -> list[int]:
        started.append(item)
        assert failed.wait(WAIT_LIMIT_TIME)
        return [item]

    async with P.Pools.using(cpu=P.Threads(workers=1), io=io_pool) as pools:
        with run_error(ValueError, "^cannot read$"):
            await outputs_of(P.io_stage(wait_for_the_failure, concurrency=4), numbers(), pools)
        # before the pools close, which cancels queued pool tasks: once a later one has run on the one
        # thread, every earlier one has run or was skipped
        await asyncio.wait_for(io_pool.run(abs, 0), WAIT_LIMIT_TIME)
        assert len(started) == 1


def twenty_numbers() -> Generator[int]:
    yield from range(20)


async def async_twenty_numbers() -> AsyncGenerator[int]:
    for item in range(20):
        yield item


def is_suspended(inputs: Generator[int] | AsyncGenerator[int]) -> bool:
    match inputs:
        case Generator():
            return inspect.getgeneratorstate(inputs) == inspect.GEN_SUSPENDED
        case AsyncGenerator():
            return inspect.getasyncgenstate(inputs) == inspect.AGEN_SUSPENDED


@pytest.mark.parametrize("make_inputs", [twenty_numbers, async_twenty_numbers], ids=["sync", "async"])
async def test_the_inputs_are_not_closed_when_a_stage_fails(
    pools: P.Pools, make_inputs: Callable[[], Generator[int] | AsyncGenerator[int]]
) -> None:
    inputs = make_inputs()
    with run_error(Failure):
        await outputs_of(P.stage(fail_on_7), inputs, pools)
    assert is_suspended(inputs)  # left where the run stopped taking items; checked in the running loop


# ------------------------------------------------------------------------- the run's scope
class ReleaseFailure(Exception):
    """The error of a backend's release."""


class FailingRelease(PicklingBackend):
    """Breaks the contract: its release raises (after releasing, so the registries end empty); counts them."""

    num_releases = 0

    @override
    def release(self, scope: str) -> None:
        self.num_releases += 1
        super().release(scope)
        raise ReleaseFailure(scope)


async def test_a_run_releases_its_scope_once_at_its_end_and_a_release_error_fails_it() -> None:
    io = FailingRelease(1)
    async with P.Pools.using(cpu=P.Threads(workers=1), io=lambda: io) as pools:
        with run_error(ReleaseFailure):
            await outputs_of(P.io_stage(inc) | P.io_stage(inc), [1, 2], pools)
        assert io.num_releases == 1  # one scope for both steps
        assert await outputs_of(P.stage(inc), [1], pools) == [2]  # no io_stage: nothing to release, no error
        assert io.num_releases == 1
    assert io.num_registered() == 0
