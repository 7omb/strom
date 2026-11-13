"""Tests of `strom._metrics.events`: the events of a run, step ids, and recorder errors."""

import asyncio
import math
from collections import Counter, defaultdict
from collections.abc import AsyncIterator, Iterable

import pytest
from helpers import (
    WAIT_LIMIT_TIME,
    CountingThreads,
    Failure,
    Tagged,
    countdown_from,
    dup,
    explode,
    inc,
    neg,
    outputs_of,
    raising_on,
    run_error,
    stats_of,
    tagged_items,
    tagged_pairs,
    text,
)
from hypothesis import given, settings
from strategies import NONEMPTY_INPUTS, stages

import strom as P
from strom.metrics import (
    Event,
    InputHandled,
    PoolTaskFinished,
    RunFinished,
    RunStarted,
    StatsRecorder,
    StepId,
    TaskFinished,
)

type TaskEvent = InputHandled | TaskFinished


def task_events(events: list[Event]) -> dict[tuple[StepId, int], list[TaskEvent]]:
    """The events of each task, by step occurrence and task index, in order."""
    by_task: defaultdict[tuple[StepId, int], list[TaskEvent]] = defaultdict(list)
    for e in events:
        if isinstance(e, (InputHandled, TaskFinished)):
            by_task[e.step_id, e.task].append(e)
    return by_task


async def test_events_of_a_run() -> None:
    events: list[Event] = []
    async with P.Pools.open(cpu_workers=1, io_workers=2) as pools:
        await outputs_of(P.io_stage(inc, concurrency=3) | P.stage(dup), range(5), pools, recorder=events.append)
    started, finished = events[0], events[-1]
    assert isinstance(started, RunStarted)
    assert isinstance(finished, RunFinished)
    assert finished.outcome == "done"
    assert [(s.within, s.index, s.name, s.concurrency) for s in started.steps] == [
        ((), 1, "inc", 3),
        ((), 2, "dup", 1),
    ]
    by_task = task_events(events)
    assert sorted((str(step_id), task) for step_id, task in by_task) == [
        ("1:inc", 0),
        ("1:inc", 1),
        ("1:inc", 2),
        ("2:dup", 0),
    ]
    for step_id in started.steps:
        own = [e for (s, _), each in by_task.items() if s == step_id for e in each]
        assert sum(isinstance(e, TaskFinished) for e in own) == step_id.concurrency
        handled = [e for e in own if isinstance(e, InputHandled)]
        assert len(handled) == 5
        assert all(e.wait_started_at <= e.started_at <= e.ended_at and e.outcome == "done" for e in handled)


def recorded[I](stage: P.Stage[I, object], inputs: Iterable[I]) -> list[Event]:
    """The events of a run (see `helpers._run_alone`)."""
    events: list[Event] = []

    async def run() -> None:
        async with P.Pools.open(cpu_workers=2, io_workers=8, cpu_backend="thread") as pools:
            await outputs_of(stage, inputs, pools, recorder=events.append)

    asyncio.run(run())
    return events


@settings(max_examples=30)
@given(stages(), NONEMPTY_INPUTS)
def test_the_events_of_each_task_partition_its_lifetime(stage: P.Stage[int, int], items: list[int]) -> None:
    events = recorded(stage, items)
    started = events[0]
    assert isinstance(started, RunStarted)
    by_task = task_events(events)
    # a run that succeeds starts every task of every step occurrence of `steps`, and only those
    assert set(by_task) == {(step_id, task) for step_id in started.steps for task in range(step_id.concurrency)}
    stats = StatsRecorder()
    for event in events:
        stats(event)
    lifetimes: defaultdict[StepId, float] = defaultdict(float)
    for (step_id, _), own in by_task.items():
        *inputs, last = own
        assert isinstance(last, TaskFinished)
        wait_started_at = own[0].wait_started_at
        for e in inputs:
            assert isinstance(e, InputHandled)
            assert e.wait_started_at == wait_started_at  # no gap and no overlap
            assert e.wait_started_at <= e.started_at <= e.ended_at
            assert 0 <= e.blocked_time <= e.ended_at - e.started_at
            wait_started_at = e.ended_at
        assert last.wait_started_at == wait_started_at
        lifetimes[step_id] += last.ended_at - own[0].wait_started_at
    # The difference of two close readings is exact (Sterbenz), so the totals differ from the lifetimes only by
    # the rounding of their sums; a reading left out or counted twice (at least tens of ns, the cost of a
    # reading) is far larger.
    for s in stats.stats().step_stats:
        assert math.isclose(s.busy_time + s.idle_time + s.blocked_time, lifetimes[s.step_id], rel_tol=1e-9)


def step_ids[I](stage: P.Stage[I, object], inputs: list[I]) -> list[str]:
    """The step ids of a run, in the order of its statistics."""
    _, stats = stats_of(stage, inputs)
    return [str(s.step_id) for s in stats.step_stats]


def test_step_ids_are_positions_in_the_stage() -> None:
    pairs = [(1, 2)]
    join = "1:product(inc, neg)"
    assert step_ids(P.product(P.io_stage(inc), P.stage(neg)) | P.stage(text), pairs) == [
        f"{join}/left/1:inc",
        f"{join}/right/1:neg",
        "2:text",
    ]
    first_product: P.Stage[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = P.first(
        P.product(P.stage(inc), P.stage(neg))
    )
    assert step_ids(first_product | P.stage(text), [((1, 2), 3)]) == [
        f"{join}/left/1:inc",
        f"{join}/right/1:neg",
        "2:text",
    ]
    outer = "1:product(product(inc, neg), inc | neg | inc)"  # its branch is longer than the outer chain
    assert step_ids(
        P.product(P.product(P.stage(inc), P.stage(neg)), P.stage(inc) | P.stage(neg) | P.stage(inc)) | P.stage(text),
        [((1, 2), 3)],
    ) == [
        f"{outer}/left/1:product(inc, neg)/left/1:inc",
        f"{outer}/left/1:product(inc, neg)/right/1:neg",
        f"{outer}/right/1:inc | neg | inc",
        "2:text",
    ]  # the branch is one fused group
    second_product: P.Stage[tuple[int, tuple[int, int]], tuple[int, tuple[int, int]]] = P.second(
        P.product(P.stage(inc), P.stage(neg))
    )
    assert step_ids(second_product | P.stage(text), [(3, (1, 2))]) == [
        f"{join}/left/1:inc",
        f"{join}/right/1:neg",
        "2:text",
    ]
    later = "1:product(duplicate | product(inc, neg), neg)"  # a join after a step inside a branch
    to_pair: P.Stage[int, tuple[int, int]] = P.duplicate()
    assert step_ids(
        P.product(to_pair | P.product(P.stage(inc), P.stage(neg)), P.stage(neg)) | P.stage(text), pairs
    ) == [
        f"{later}/left/1:duplicate",
        f"{later}/left/2:product(inc, neg)/left/1:inc",
        f"{later}/left/2:product(inc, neg)/right/1:neg",
        f"{later}/right/1:neg",
        "2:text",
    ]
    ev_inc, ev_neg, ev_dup = P.stage(inc), P.stage(neg), P.stage(dup)
    assert (
        step_ids((ev_inc | ev_neg) | ev_dup, [1]) == step_ids(ev_inc | (ev_neg | ev_dup), [1]) == ["1:inc | neg | dup"]
    )
    io_inc, io_neg = P.io_stage(inc), P.io_stage(neg)  # never fused
    unfused = ["1:inc", "2:inc", "3:neg"]
    assert step_ids((ev_inc | io_inc) | io_neg, [1]) == step_ids(ev_inc | (io_inc | io_neg), [1]) == unfused
    route = "1:route(inc, neg | inc)"
    assert step_ids(P.route(P.io_stage(inc), P.stage(neg) | P.stage(inc)) | P.untag(), tagged_items()) == [
        f"{route}/left/1:inc",
        f"{route}/right/1:neg | inc",
        "2:untag",
    ]
    first_route: P.Stage[tuple[Tagged, int], tuple[Tagged, int]] = P.first(
        P.route(P.io_stage(inc), P.stage(neg) | P.stage(inc))
    )
    assert step_ids(first_route, tagged_pairs()) == [
        f"{route}/left/1:inc",
        f"{route}/right/1:neg | inc",
    ]


def test_step_ids_inside_gather_and_loop() -> None:
    gathered = "1:gather(inc | neg)"
    assert step_ids(P.gather(P.io_stage(inc) | P.stage(neg)) | P.stage(text), [1]) == [
        f"{gathered}/body/1:inc",
        f"{gathered}/body/2:neg",
        "2:text",
    ]
    fused = "1:gather(inc | neg)"  # the body is one fused group
    assert step_ids(P.gather(P.stage(inc) | P.stage(neg)) | P.stage(text), [1]) == [
        f"{fused}/body/1:inc | neg",
        "2:text",
    ]
    looped = "1:loop(countdown_from)"
    first_loop: P.Stage[tuple[int, int], tuple[int, int]] = P.first(P.loop(P.io_stage(countdown_from)))
    assert step_ids(first_loop, [(1, 0)]) == [f"{looped}/body/1:countdown_from"]
    in_branch = "1:product(loop(countdown_from), inc)"
    assert step_ids(P.product(P.loop(P.io_stage(countdown_from)), P.stage(inc)), [(1, 0)]) == [
        f"{in_branch}/left/1:loop(countdown_from)/body/1:countdown_from",
        f"{in_branch}/right/1:inc",
    ]


def final_events(events: list[Event], name: str) -> Counter[str]:
    """How the inputs and tasks of the step `name` ended: counts of the event kinds (with the outcome)."""
    return Counter(
        f"InputHandled {e.outcome}" if isinstance(e, InputHandled) else type(e).__name__
        for e in events
        if isinstance(e, (InputHandled, TaskFinished)) and e.step_id.name == name
    )


async def fail_after_two(item: int) -> AsyncIterator[int]:
    yield item
    yield item
    raise Failure(item)


async def test_a_failed_input_keeps_its_outputs_and_time() -> None:
    async def slow(item: int) -> AsyncIterator[int]:
        await asyncio.sleep(0.01)  # the handling takes at least 10 ms: a lower bound of its recorded time
        async for out in fail_after_two(item):
            yield out

    events: list[Event] = []
    async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
        with run_error(Failure):
            await outputs_of(P.async_stage(slow), [1], pools, recorder=events.append)
    (handled,) = [e for e in events if isinstance(e, InputHandled)]
    assert (handled.outcome, handled.num_items_out) == ("failed", 2)
    assert handled.ended_at - handled.started_at >= 0.01
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.outcome == "failed"


async def test_every_task_that_ran_records_its_end() -> None:
    async def inputs() -> AsyncIterator[int]:
        yield 0
        await asyncio.Event().wait()  # never ends: the second task waits for input until cancelled

    events: list[Event] = []
    async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
        with run_error(Failure):
            await outputs_of(P.async_stage(fail_after_two, concurrency=2), inputs(), pools, recorder=events.append)
    assert final_events(events, "fail_after_two") == Counter({"InputHandled failed": 1, "TaskFinished": 2})
    for own in task_events(events).values():
        assert isinstance(own[-1], TaskFinished)
        assert own[-1].wait_started_at == (own[-2].ended_at if len(own) > 1 else own[0].wait_started_at)


async def test_a_put_waiting_for_downstream_counts_as_blocked() -> None:
    async def three(item: int) -> AsyncIterator[int]:
        for _ in range(3):
            yield item

    events: list[Event] = []
    async with (
        P.Pools.open(cpu_workers=1, io_workers=1) as pools,
        P.stream(P.async_stage(three, buffer_size=1), [1], pools, recorder=events.append) as outputs,
    ):
        async for _ in outputs:
            # downstream takes an output every 20 ms: the step's third put waits for the second output to be
            # taken, at least about 20 ms (half of it as the bound: the put starts a moment after the sleep)
            await asyncio.sleep(0.02)
    (handled,) = [e for e in events if isinstance(e, InputHandled)]
    assert (handled.outcome, handled.num_items_out) == ("done", 3)
    assert 0.01 <= handled.blocked_time <= handled.ended_at - handled.started_at


async def test_a_put_cancelled_while_waiting_counts_as_blocked() -> None:
    async def endless(item: int) -> AsyncIterator[int]:
        while True:
            yield item

    events: list[Event] = []
    async with (
        P.Pools.open(cpu_workers=1, io_workers=1) as pools,
        P.stream(P.async_stage(endless, buffer_size=1), [1], pools, recorder=events.append) as outputs,
    ):
        async for _ in outputs:
            break
        for _ in range(3):  # the step refills its output queue and waits in a put
            await asyncio.sleep(0)
        await asyncio.sleep(0.01)  # the put waits at least 10 ms; leaving the block then cancels it
    (handled,) = [e for e in events if isinstance(e, InputHandled)]
    assert handled.outcome == "cancelled"
    assert 0.01 <= handled.blocked_time <= handled.ended_at - handled.started_at
    finished = events[-1]
    assert isinstance(finished, RunFinished)
    assert finished.outcome == "cancelled"  # left early


async def test_an_input_cancelled_by_a_failure_is_recorded() -> None:
    barrier = asyncio.Barrier(2)

    async def meet(item: int) -> AsyncIterator[int]:  # both inputs handled at once; one fails, one is cancelled
        async with asyncio.timeout(WAIT_LIMIT_TIME):
            await barrier.wait()
        if item == 0:
            raise Failure(item)
        async with asyncio.timeout(WAIT_LIMIT_TIME):  # until the failure cancels it
            await asyncio.Event().wait()
        yield item

    events: list[Event] = []
    async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
        with run_error(Failure):
            await outputs_of(P.async_stage(meet, concurrency=2), [0, 1], pools, recorder=events.append)
    assert final_events(events, "meet") == Counter(
        {"InputHandled failed": 1, "InputHandled cancelled": 1, "TaskFinished": 2}
    )
    assert isinstance(events[-1], RunFinished)


async def test_an_input_whose_pool_task_is_skipped_is_recorded_as_cancelled() -> None:
    io_pool = CountingThreads(workers=1)
    started: list[int] = []

    def fail_once_both_queued(item: int) -> list[int]:
        """Fails once the second task's pool task waits behind it in the one-thread pool, where it is skipped."""
        started.append(item)
        assert io_pool.wait_until_submitted(2), "the second pool task was never queued"
        raise Failure(item)

    events: list[Event] = []
    async with P.Pools.open_on(cpu=P.Threads(workers=1), io=io_pool) as pools:
        with run_error(Failure):
            await outputs_of(
                P.io_stage(fail_once_both_queued, concurrency=2),
                [0, 1],
                pools,
                recorder=events.append,
            )
    assert len(started) == 1
    assert final_events(events, "fail_once_both_queued") == Counter(
        {"InputHandled failed": 1, "InputHandled cancelled": 1, "TaskFinished": 2}
    )


@pytest.mark.parametrize(
    "kind, stage, expected",
    [
        (RunStarted, P.stage(inc), [("RecorderFailure", [])]),
        (InputHandled, P.stage(inc), [("RecorderFailure", ["in stage 'inc'"])]),
        (PoolTaskFinished, P.io_stage(inc), [("RecorderFailure", ["in stage 'inc'"])]),
        (TaskFinished, P.stage(inc), [("RecorderFailure", ["in stage 'inc'"])]),
        (
            InputHandled,
            P.stage(explode),
            [("RecorderFailure", ["in stage 'explode'"]), ("ValueError", ["in stage 'explode'"])],
        ),
        (RunFinished, P.stage(explode), [("RecorderFailure", []), ("ValueError", ["in stage 'explode'"])]),
    ],
    ids=["RunStarted", "InputHandled", "PoolTaskFinished", "TaskFinished", "InputHandled of a failure", "RunFinished"],
)
async def test_recorder_errors_end_the_run_like_user_errors(
    kind: type[Event], stage: P.Stage[int, object], expected: list[tuple[str, list[str]]]
) -> None:
    async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
        with pytest.raises(ExceptionGroup) as info:
            # a single step: a chain of event-loop steps would be fused (see the next test)
            await outputs_of(stage, [1], pools, recorder=raising_on(kind, stage.name))
    assert isinstance(info.value, P.RunFailed)
    errors = info.value.exceptions  # the user's error is never lost
    assert sorted((type(e).__name__, getattr(e, "__notes__", [])) for e in errors) == expected


async def test_recorder_errors_in_a_group_name_the_group() -> None:
    async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
        with pytest.raises(ExceptionGroup) as info:
            await outputs_of(
                P.stage(inc) | P.stage(explode), [1], pools, recorder=raising_on(InputHandled, "inc | explode")
            )
    assert isinstance(info.value, P.RunFailed)
    assert sorted((type(e).__name__, getattr(e, "__notes__", [])) for e in info.value.exceptions) == [
        ("RecorderFailure", ["in stage 'inc | explode'"]),
        ("ValueError", ["in stage 'inc | explode'"]),
    ]
