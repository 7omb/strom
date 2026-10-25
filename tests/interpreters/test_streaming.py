"""Tests of `strom._interpreters.streaming`: runs agree with the reference semantics; concurrency,
backpressure and memory of steps, joins, routes, gathers and loops; failures and cancellation of runs."""

import asyncio
import contextvars
import inspect
import math
import threading
import time
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Generator, Iterator
from contextlib import suppress
from typing import Literal, cast, override

import helpers
import pytest
from helpers import (
    SATURATION_GRACE_TIME,
    WAIT_LIMIT_TIME,
    Countdown,
    Failure,
    Tagged,
    add_pair,
    async_inc,
    at_most_three_lazily,
    bag,
    boom,
    collect,
    collect_pickling,
    double,
    explode,
    fail_on_7,
    inc,
    meaning,
    neg,
    outputs_of,
    run_error,
    slow_double,
    tagged_items,
    tagged_pairs,
    to_right,
    tracked_a,
    tracked_b,
)
from hypothesis import example, given, settings
from hypothesis import strategies as st
from strategies import NONEMPTY_INPUTS, maps, stages

import strom as P
from strom._interpreters.failures import run_errors
from strom._stages.focus import Focus
from strom._stages.model import Join


def one_left_one_right() -> list[Tagged]:
    return [P.Left(1), P.Right(2)]


def never(_: int) -> bool:
    return False


def split_in_two(countdown: Countdown) -> list[P.Left[Countdown] | P.Right[int]]:
    """Feeds back two items per item while the depth lasts: 2 ** depth outputs per input."""
    item, depth = countdown
    return [P.Left((item, depth - 1)), P.Left((item + 1, depth - 1))] if depth > 0 else [P.Right(item)]


def jittery_neg(item: int) -> list[int]:
    """Sleeps 0-3 ms depending on the item, so that results leave a branch out of order."""
    time.sleep(0.001 * (item % 4))
    return [-item]


def tracked_c(item: int) -> list[int]:
    return [helpers.TRACK.run("c", item)]


class TimerRecordingLoop(asyncio.SelectorEventLoop):
    """An event loop recording the delays of the timers scheduled while `recording` is set: asyncio schedules
    every wait that ends by time (`sleep`, `timeout`, `wait_for`) through `call_at`."""

    def __init__(self) -> None:
        super().__init__()
        self.recording = False
        self.delays: list[float] = []

    @override
    def call_at[*Ts](
        self, when: float, callback: Callable[[*Ts], object], *args: *Ts, context: contextvars.Context | None = None
    ) -> asyncio.TimerHandle:
        if self.recording:
            self.delays.append(when - self.time())
        return super().call_at(when, callback, *args, context=context)


def agrees_with_meaning[I](
    stage: P.Stage[I, object], inputs: list[I], cpu_backend: P.CpuBackendKind = "thread"
) -> bool:
    """A run of `stage` on `inputs` produces the same items (in any order) as its reference semantics."""
    return bag(collect(stage, inputs, cpu_backend=cpu_backend)) == bag(meaning(stage, inputs))


# ------------------------------------------------------------------------------ results
def test_product_matches_results_of_the_same_input_despite_reordering() -> None:
    stage = P.product(P.io_stage(jittery_neg, concurrency=8) | P.stage(inc), P.io_stage(jittery_neg, concurrency=3))
    outputs = collect(stage, [(i, 10 * i) for i in range(200)], io_workers=16)
    assert sorted(outputs) == sorted((-i + 1, -10 * i) for i in range(200))


@given(stages(), NONEMPTY_INPUTS)
# pinned: a concurrent step with a full output queue in front of a slower step (backpressure)
@example(P.io_stage(double, concurrency=2, buffer_size=1) | P.io_stage(slow_double), list(range(30)))
def test_runs_agree_with_reference_semantics(stage: P.Stage[int, int], items: list[int]) -> None:
    assert agrees_with_meaning(stage, items)


def test_runs_without_inputs() -> None:
    pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
    lifted: P.Stage[tuple[int, int], tuple[int, int]] = P.first(P.stage(neg))
    stage = (
        P.io_stage(at_most_three_lazily, concurrency=2)
        | pairs
        | P.product(P.cpu_stage(inc), P.async_stage(async_inc))
        | lifted
        | P.stage(add_pair)
    )
    assert collect(stage, []) == meaning(stage, []) == []
    assert collect(stage, [0]) == meaning(stage, [0]) == []  # an input without outputs


@given(stages(ordered=True), NONEMPTY_INPUTS)
def test_concurrency_one_preserves_reference_order(stage: P.Stage[int, int], items: list[int]) -> None:
    assert collect(stage, items) == meaning(stage, items)


@given(stages(), st.lists(st.integers(0, 10), min_size=1, max_size=15))
def test_failures_surface_the_users_error(stage: P.Stage[int, int], items: list[int]) -> None:
    failing = P.io_stage(fail_on_7, concurrency=4) | stage
    if 7 not in items:
        collect(failing, items)
        return
    with pytest.raises(ExceptionGroup) as info:
        collect(failing, items)
    assert isinstance(info.value, P.RunFailed)
    for error in info.value.exceptions:  # only the user's errors, each naming the failing step
        assert isinstance(error, Failure)
        assert "in stage 'fail_on_7'" in error.__notes__


@settings(max_examples=15)
@given(maps(), NONEMPTY_INPUTS)
def test_process_backend_agrees_with_reference_semantics(stage: P.Stage[int, int], items: list[int]) -> None:
    assert agrees_with_meaning(stage, items, cpu_backend="process")


@settings(max_examples=30)
@given(stages(), NONEMPTY_INPUTS)
def test_a_backend_without_shared_memory_agrees_with_reference_semantics(
    stage: P.Stage[int, int], items: list[int]
) -> None:
    """Both resources on `PicklingBackend`s: every call pickled, iterators routed to their worker; no worker
    keeps an iterator afterwards (checked by `collect_pickling`)."""
    assert bag(collect_pickling(stage, items)) == bag(meaning(stage, items))


# --------------------------------------------------------- concurrency and backpressure
def test_streaming_concurrency_limit() -> None:
    with helpers.TRACK.saturating({"a": 4}):  # 30 items and 16 pool threads: only the limit keeps it at 4
        collect(P.io_stage(tracked_a, concurrency=4), range(30), io_workers=16)
    assert helpers.TRACK.num_max_active["a"] == 4


def test_async_stage_concurrency_limit() -> None:
    num_active, num_max_active = 0, 0

    async def run() -> None:
        saturated, gate = asyncio.Event(), asyncio.Event()  # three calls inside; the calls may leave

        async def tracked(item: int) -> AsyncIterator[int]:
            nonlocal num_active, num_max_active
            num_active += 1
            num_max_active = max(num_max_active, num_active)
            if num_active == 3:
                saturated.set()
            await gate.wait()
            num_active -= 1
            yield item

        async def release_when_saturated() -> None:
            """As `Tracker.saturating`: waits for the limit, then `SATURATION_GRACE_TIME` for calls above it."""
            with suppress(TimeoutError):  # never saturated: the assertion on `num_max_active` fails
                async with asyncio.timeout(WAIT_LIMIT_TIME):
                    await saturated.wait()
            await asyncio.sleep(SATURATION_GRACE_TIME)
            gate.set()

        release = asyncio.create_task(release_when_saturated())
        async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
            await outputs_of(P.async_stage(tracked, concurrency=3), range(30), pools)
        await release

    asyncio.run(run())
    assert num_max_active == 3


def test_product_branch_steps_use_their_own_concurrency_at_the_same_time() -> None:
    left = P.io_stage(tracked_a, concurrency=3) | P.io_stage(tracked_b, concurrency=2)
    stage = P.product(left, P.io_stage(tracked_c, concurrency=4))
    # `a` fills up first; `b` only gets items from `a`. Then `b` and the right branch are held together.
    with helpers.TRACK.saturating({"a": 3}, {"b": 2, "c": 4}):
        outputs = collect(stage, [(i, i) for i in range(40)], io_workers=32)
    assert sorted(outputs) == [(i, i) for i in range(40)]
    assert (
        helpers.TRACK.num_max_active["a"],
        helpers.TRACK.num_max_active["b"],
        helpers.TRACK.num_max_active["c"],
    ) == (3, 2, 4)
    assert helpers.TRACK.num_calls["a"] == helpers.TRACK.num_calls["c"] == 40  # each branch once per input


def test_product_branches_run_simultaneously() -> None:
    meeting = threading.Barrier(2, timeout=WAIT_LIMIT_TIME)  # passes only when both branches are inside at once

    def left(item: int) -> list[int]:
        meeting.wait()
        return [item]

    def right(item: int) -> list[int]:
        meeting.wait()
        return [item * 10]

    pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
    outputs = collect(pairs | P.product(P.io_stage(left), P.io_stage(right)), [3])
    assert outputs == [(3, 30)]


def test_route_branches_run_simultaneously() -> None:
    meeting = threading.Barrier(2, timeout=WAIT_LIMIT_TIME)  # passes only when both branches are inside at once

    def meet(item: int) -> list[int]:
        meeting.wait()
        return [item]

    outputs = collect(P.route(P.io_stage(meet), P.io_stage(meet)), one_left_one_right())
    assert bag(outputs) == bag([P.Left(1), P.Right(2)])


def test_product_with_small_buffers_and_unbalanced_branches() -> None:
    stage = P.product(P.stage(neg), P.io_stage(tracked_a, concurrency=4), buffer_size=1)
    with helpers.TRACK.saturating({"a": 4}):  # the right branch stalls while the left one runs ahead into full buffers
        outputs = collect(stage, [(i, i) for i in range(100)])
    assert bag(outputs) == bag([(-i, i) for i in range(100)])


def test_product_feeds_a_branch_while_the_other_branch_is_full() -> None:
    released = threading.Event()  # set by the right branch once it got a third input
    right_inputs: list[int] = []

    def left(item: int) -> list[int]:
        if not released.wait(WAIT_LIMIT_TIME):
            raise TimeoutError("the right branch did not get its third input")
        return [item]

    def right(item: int) -> list[int]:
        right_inputs.append(item)
        if len(right_inputs) == 3:
            released.set()
        return [item]

    # The left branch holds input 0 and its queue input 1; input 2 must still reach the right branch.
    stage = P.product(P.io_stage(left), P.io_stage(right), buffer_size=1)
    outputs = collect(stage, [(i, i) for i in range(5)])
    assert bag(outputs) == bag([(i, i) for i in range(5)])


class Token:
    """Counts its live instances (CPython frees an object as soon as its last reference is gone)."""

    num_live = 0

    def __init__(self) -> None:
        Token.num_live += 1

    def __del__(self) -> None:
        Token.num_live -= 1


@pytest.mark.parametrize("tokens_side", ["left", "right"])
def test_product_keeps_results_only_while_the_other_branch_may_still_deliver(tokens_side: str) -> None:
    # One input: one branch emits 1000 tokens, the other one result once 200 tokens are out. The first
    # 200 must be kept until that result arrives; later tokens are freed once passed on (were: all kept).
    other_released = asyncio.Event()
    num_live_before = Token.num_live  # independent of tokens other tests may have left alive

    def tokens(_: int) -> Iterator[Token]:
        for i in range(1000):
            if i == 200:
                other_released.set()
            yield Token()

    async def released(item: int) -> AsyncIterator[int]:
        async with asyncio.timeout(WAIT_LIMIT_TIME):
            await other_released.wait()
        yield item

    num_live_per_output: list[int] = []

    def note_live(_: object) -> list[object]:
        num_live_per_output.append(Token.num_live - num_live_before)
        return []

    join = (
        P.product(P.stage(tokens), P.async_stage(released))
        if tokens_side == "left"
        else P.product(P.async_stage(released), P.stage(tokens))
    )
    assert collect(join | P.stage(note_live), [(0, 0)]) == []
    assert len(num_live_per_output) == 1000
    assert max(num_live_per_output[400:]) < 100  # tokens in queues only (were: up to 1000)


@pytest.mark.parametrize("late_side", ["right", "left"])
def test_product_puts_each_pair_as_it_is_merged(late_side: str) -> None:
    # One late result of one branch meets n stored results of the other: each pair is merged when the output queue can
    # take it (were: all n merged before the first was put). A join of the given focus counts its merges.
    n = 50
    num_merges = 0

    def split(item: int) -> tuple[tuple[int, int], None]:
        return (item, item), None

    def merge(pair: tuple[int, int], _: None) -> tuple[int, int]:
        nonlocal num_merges
        num_merges += 1
        return pair

    released = asyncio.Event()

    def many(_: int) -> Iterator[int]:
        for i in range(n):
            if i == n - 1:
                released.set()
            yield i

    async def late(item: int) -> AsyncIterator[int]:
        async with asyncio.timeout(WAIT_LIMIT_TIME):
            await released.wait()
        yield item

    stored, late_one = P.stage(many), P.async_stage(late)
    first, second = (stored, late_one) if late_side == "right" else (late_one, stored)
    join: Join[int, tuple[int, int], int, int, int, int, None] = Join(
        name="join", left=first, right=second, focus=Focus(split, merge, None), buffer_size=1
    )
    in_flight: list[int] = []  # pairs merged but not yet received, at each output

    def note(_: object) -> list[object]:
        in_flight.append(num_merges - len(in_flight) - 1)
        return []

    assert collect(join | P.stage(note), [0]) == []
    assert len(in_flight) == n
    assert max(in_flight) <= 2  # the output queue's capacity and the pair being put (was: n - 1)


def tracked_a_to_right(item: int) -> list[P.Right[int]]:
    return [P.Right(helpers.TRACK.run("a", item))]


@pytest.mark.parametrize("kind", ["gather", "loop"])
def test_gather_and_loop_limit_their_inputs_in_flight(kind: str) -> None:
    # the body could take 8 inputs at once; only the limit of the gather or loop keeps it at 3
    stage: P.Stage[int, object] = (
        P.gather(P.io_stage(tracked_a, concurrency=8), concurrency=3)
        if kind == "gather"
        else P.loop(P.io_stage(tracked_a_to_right, concurrency=8), concurrency=3)
    )
    with helpers.TRACK.saturating({"a": 3}):
        collect(stage, range(30), io_workers=16)
    assert helpers.TRACK.num_max_active["a"] == 3


@pytest.mark.parametrize("kind", ["gather", "loop"])
def test_gather_and_loop_take_no_inputs_beyond_their_limit_while_downstream_waits(kind: str) -> None:
    """While the consumer is held, the inputs are taken only as far as the queues and the inputs in flight allow.

    A gather whose body drops every item completes each input at once; its input stays in flight until
    its list is put, else its lists would collect without bound. A loop's body input queue is
    unbounded; only the limit on inputs in flight bounds it. The consumer's sleep is intentional: it
    gives the run the time to take all inputs if nothing held it back (far more than needed)."""
    num_taken = 0

    def numbers() -> Iterator[int]:
        nonlocal num_taken
        for i in range(1000):
            num_taken += 1
            yield i

    num_taken_when_released: list[int] = []

    def held(item: object) -> list[object]:
        if not num_taken_when_released:
            time.sleep(0.2)
            num_taken_when_released.append(num_taken)
        return [item]

    stage: P.Stage[int, object] = (
        P.gather(P.where(never), concurrency=3, buffer_size=1)
        if kind == "gather"
        else P.loop(P.io_stage(to_right), concurrency=3, buffer_size=1)
    )
    assert len(collect(stage | P.io_stage(held), numbers())) == 1000
    # the queue of the inputs, the inputs in flight, the output queue, the consumer and the items in hand
    assert num_taken_when_released[0] <= 10 + 3 + 1 + 1 + 3


def identity_tagged(item: P.Left[Countdown] | P.Right[int]) -> list[P.Left[Countdown] | P.Right[int]]:
    return [item]


def test_loop_feedback_never_waits_for_room_in_the_body() -> None:
    """Queues of size 1 and a body feeding back two items per item: feedback that waited for room in the
    body's input queue would block the loop on itself (an artificial deadlock)."""
    body = P.io_stage(split_in_two, buffer_size=1) | P.io_stage(identity_tagged, buffer_size=1)
    looped = P.loop(body, buffer_size=1)

    async def run() -> list[object]:
        async with P.Pools.open(cpu_workers=1, io_workers=4, cpu_backend="thread") as pools:
            async with asyncio.timeout(WAIT_LIMIT_TIME):
                return [*await outputs_of(looped, [(i, 5) for i in range(10)], pools)]

    assert bag(asyncio.run(run())) == bag([i + j for i in range(10) for j in range(6) for _ in range(math.comb(5, j))])


def test_same_stage_object_used_several_times() -> None:
    # Each occurrence has its own limit of 2: the barrier opens only when both hold two calls at once, and
    # in a join both branches hold two calls at once.
    meeting = threading.Barrier(4, timeout=WAIT_LIMIT_TIME)

    def shift_or_meet(item: int) -> list[int]:
        """The first occurrence shifts items by 100: 0 and 1 pass at once (and wait in the second
        occurrence as 100 and 101), 2 and 3 wait in the first one."""
        if item in (2, 3, 100, 101):
            meeting.wait()
        return [item + 100 if item < 100 else item]

    s = P.io_stage(shift_or_meet, concurrency=2)
    assert sorted(collect(s | s, range(4))) == [100, 101, 102, 103]
    pairs = [(i, i) for i in range(5)]
    tracked = P.io_stage(tracked_a, concurrency=2)
    with helpers.TRACK.saturating({"a": 4}):
        assert sorted(collect(P.product(tracked, tracked), pairs)) == pairs
    assert helpers.TRACK.num_max_active["a"] == 4


@pytest.mark.parametrize("fed_by", ["event-loop step", "lifted event-loop step", "inputs"])
@pytest.mark.parametrize("concurrency", [1, 6])
def test_event_loop_steps_buffer_twice_the_consumers_concurrency_at_least_ten(concurrency: int, fed_by: str) -> None:
    """While all tasks of the consumer wait, (endless) items from an event-loop step, or the run's
    inputs, run ahead by: the consumer's inputs, its queue of twice their number but at least 10, and
    one item waiting to be put."""
    num_produced = 0

    def numbers() -> Iterator[int]:
        nonlocal num_produced
        while True:
            num_produced += 1
            yield num_produced

    def endless(_: None) -> Iterator[int]:
        return numbers()

    async def run() -> int:
        release = asyncio.Event()
        num_started = 0

        async def hold(item: int) -> AsyncIterator[int]:
            nonlocal num_started
            num_started += 1
            async with asyncio.timeout(WAIT_LIMIT_TIME):  # held until the run is cancelled
                await release.wait()
            yield item

        async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
            consumer = P.async_stage(hold, concurrency=concurrency)
            pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
            lifted: P.Stage[tuple[int, int], tuple[int, int]] = P.first(consumer)

            async def run_fed() -> None:
                match fed_by:
                    case "event-loop step":
                        await outputs_of(P.stage(endless) | consumer, [None], pools)
                    case "lifted event-loop step":
                        await outputs_of(P.stage(endless) | pairs | lifted, [None], pools)
                    case _:
                        await outputs_of(consumer, numbers(), pools)

            run_task = asyncio.create_task(run_fed())
            async with asyncio.timeout(WAIT_LIMIT_TIME):
                while num_started < concurrency:
                    await asyncio.sleep(0)  # lets the run start
            for _ in range(5):
                await asyncio.sleep(0)  # lets the producer fill its queue (one pass of the loop is enough)
            num_ahead = num_produced
            run_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await run_task
            return num_ahead

    assert asyncio.run(run()) == concurrency + max(10, 2 * concurrency) + 1


# ----------------------------------------------------------------------------- failures
def test_a_single_error_is_raised_in_the_runs_group_with_stage_note() -> None:
    with run_error(ValueError, "boom") as info:
        collect(P.io_stage(inc) | P.io_stage(boom, name="checker"), range(10))
    assert info.value.exceptions[0].__notes__ == ["in stage 'checker'"]


def raises_a_group(item: int) -> list[int]:
    raise ExceptionGroup("the user's group", [ValueError("a"), KeyError("b")])


def test_a_users_exception_group_stays_whole() -> None:
    # The run's group holds the user's group as raised (message, errors), with the stage note on it.
    with pytest.RaisesGroup(
        pytest.RaisesGroup(ValueError, KeyError, match="^the user's group\nin stage"),
        check=lambda group: isinstance(group, P.RunFailed),
    ) as info:
        collect(P.io_stage(raises_a_group), [1])
    (users_group,) = info.value.exceptions
    assert users_group.__notes__ == ["in stage 'raises_a_group'"]


def test_run_errors_remove_only_the_groups_of_the_runs_task_groups() -> None:
    users = ExceptionGroup("the user's group", [KeyError("a")])  # recorded when it ended the run
    unrecorded = AssertionError("an internal check")
    nested = ExceptionGroup("task group", [ExceptionGroup("inner", [users]), ExceptionGroup("x", [unrecorded])])
    assert run_errors(nested, [users]) == [users, unrecorded]


def duplicated() -> P.Stage[int, tuple[int, int]]:
    return P.duplicate()


def first_of_product() -> P.Stage[tuple[tuple[int, int], int], tuple[tuple[int, int], int]]:
    return P.first(P.product(P.io_stage(boom), P.stage(neg)))


def lifted_boom() -> P.Stage[tuple[int, int], tuple[int, int]]:
    return P.first(P.io_stage(boom))


def first_of_route() -> P.Stage[tuple[Tagged, int], tuple[Tagged, int]]:
    return P.first(P.route(P.io_stage(boom), P.stage(neg)))


def first_of_gather() -> P.Stage[tuple[int, int], tuple[list[int], int]]:
    return P.first(P.gather(P.io_stage(boom)))


type Interpreter = Literal["run", "reference"]


def fail_on[I](interpreter: Interpreter, stage: P.Stage[I, object], inputs: list[I]) -> None:
    """A run of `stage` on `inputs`, or its reference semantics (both must raise the same group)."""
    if interpreter == "run":
        collect(stage, inputs)
    else:
        meaning(stage, inputs)


@pytest.mark.parametrize(
    "fail, notes",
    [
        (
            lambda interpreter: fail_on(interpreter, duplicated() | P.product(P.io_stage(inc), P.io_stage(boom)), [2]),
            ["in stage 'boom'", "in stage 'product(inc, boom)'"],
        ),
        (
            lambda interpreter: fail_on(
                interpreter, P.product(P.product(P.io_stage(boom), P.stage(neg)), P.stage(neg)), [((2, 2), 0)]
            ),
            ["in stage 'boom'", "in stage 'product(boom, neg)'", "in stage 'product(product(boom, neg), neg)'"],
        ),
        (
            lambda interpreter: fail_on(interpreter, first_of_product(), [((2, 2), 0)]),
            ["in stage 'boom'", "in stage 'product(boom, neg)'"],
        ),  # not repeated
        (
            lambda interpreter: fail_on(interpreter, lifted_boom(), [(2, 0)]),
            ["in stage 'boom'"],
        ),  # lifted steps keep their name
        # a single event-loop step is not fused (a group's errors name the group)
        (lambda interpreter: fail_on(interpreter, P.stage(explode), [1]), ["in stage 'explode'"]),
        (
            lambda interpreter: fail_on(interpreter, P.route(P.io_stage(inc), P.io_stage(boom)), tagged_items()),
            ["in stage 'boom'", "in stage 'route(inc, boom)'"],
        ),
        (
            lambda interpreter: fail_on(interpreter, first_of_route(), tagged_pairs()),
            ["in stage 'boom'", "in stage 'route(boom, neg)'"],
        ),  # not repeated
        (
            lambda interpreter: fail_on(interpreter, P.gather(P.io_stage(boom)), [2]),
            ["in stage 'boom'", "in stage 'gather(boom)'"],
        ),
        (
            lambda interpreter: fail_on(interpreter, first_of_gather(), [(2, 0)]),
            ["in stage 'boom'", "in stage 'gather(boom)'"],
        ),  # not repeated
        (
            lambda interpreter: fail_on(interpreter, P.loop(P.io_stage(boom) | P.stage(to_right)), [2]),
            ["in stage 'boom'", "in stage 'loop(boom | to_right)'"],
        ),
    ],
    ids=[
        "product branch",
        "nested product",
        "first of product",
        "lifted step",
        "stage",
        "route branch",
        "first of route",
        "gather body",
        "first of gather",
        "loop body",
    ],
)
@pytest.mark.parametrize("interpreter", ["run", "reference"])
def test_error_notes_name_the_stages(
    fail: Callable[[Interpreter], object], notes: list[str], interpreter: Interpreter
) -> None:
    # the same notes from both interpreters (no case has a fused group: a run names a group by its chain)
    with run_error(ValueError, r"^(boom|stage failed)\b") as info:
        fail(interpreter)
    assert info.value.exceptions[0].__notes__ == notes


def test_route_rejects_items_that_are_not_tagged() -> None:
    """The types forbid such inputs; if untyped code passes them (here: casts), they must raise, not vanish."""
    route = P.route(P.stage(inc), P.stage(inc))
    lifted: P.Stage[tuple[Tagged, int], tuple[Tagged, int]] = P.first(route)
    untagged = cast(list[Tagged], [1, 2])
    untagged_pairs = cast(list[tuple[Tagged, int]], [(1, 0)])
    with run_error(AssertionError, "unreachable"):
        collect(route, untagged)
    with run_error(AssertionError, "unreachable"):
        meaning(route, untagged)
    with run_error(AssertionError, "unreachable"):
        collect(lifted, untagged_pairs)
    with run_error(AssertionError, "unreachable"):
        meaning(lifted, untagged_pairs)
    not_a_pair = cast(list[tuple[Tagged, int]], [(P.Left(1), 0, 0)])
    with run_error(ValueError, "too many values to unpack"):
        collect(lifted, not_a_pair)
    with run_error(ValueError, "too many values to unpack"):
        meaning(lifted, not_a_pair)


def test_loop_rejects_outputs_that_are_not_tagged() -> None:
    """The types forbid such outputs of its body; if untyped code emits them (here: a cast), they must raise."""
    looped = P.loop(cast(P.Stage[int, P.Left[int] | P.Right[int]], P.io_stage(inc)))
    with run_error(AssertionError, "unreachable"):
        collect(looped, [1])
    with run_error(AssertionError, "unreachable"):
        meaning(looped, [1])


def test_inputs_completing_while_a_failed_run_is_cancelled_raise_nothing() -> None:
    # Cancelling a body step that holds the last item of an input completes the input (in the step's
    # `finish`); that must not raise, also after the internal loops of the gather or the loop were cancelled.
    holding = threading.Event()

    async def hold(item: int) -> AsyncIterator[P.Right[int]]:
        holding.set()
        await asyncio.Event().wait()  # until cancelled
        yield P.Right(item)

    def fail_once_held(item: int) -> list[int]:
        if item == 7:
            assert holding.wait(WAIT_LIMIT_TIME)
            raise Failure(item)
        return [item]

    stages: list[P.Stage[int, object]] = [P.gather(P.async_stage(hold)), P.loop(P.async_stage(hold))]
    for stage in stages:
        holding.clear()
        with run_error(Failure):
            collect(P.io_stage(fail_once_held) | stage, [1, 7])


# ------------------------------------------------------------- closing and cancellation
type EndlessStage = tuple[Callable[[int], P.Stage[None, int]], Callable[[], bool], Callable[[], int]]


@pytest.fixture(params=["sync", "async", "io"])
def endless_stage(request: pytest.FixtureRequest) -> EndlessStage:
    """A function building a stage that emits endlessly for its one input (with a buffer size; on the
    event loop it has none) on the event loop, async, or on the io pool, a function telling whether the
    one generator it created has been closed (for "io", closed in a pool thread: waits for it), and the
    number of items it made."""
    gens: list[Generator[int]] = []
    agens: list[AsyncGenerator[int]] = []
    closed = threading.Event()
    num_made = 0

    def numbers() -> Generator[int]:
        nonlocal num_made
        while True:
            num_made += 1
            yield num_made

    async def async_numbers() -> AsyncGenerator[int]:
        nonlocal num_made
        while True:
            num_made += 1
            yield num_made

    def made() -> int:
        return num_made

    def make_items(_: None) -> Iterator[int]:
        gens.append(numbers())
        return gens[-1]

    def is_closed() -> bool:
        return len(gens) == 1 and inspect.getgeneratorstate(gens[0]) == inspect.GEN_CLOSED

    if request.param == "sync":
        return lambda _: P.stage(make_items), is_closed, made
    if request.param == "io":

        def make_watched_items(_: None) -> Iterator[int]:
            try:
                yield from make_items(None)
            finally:
                closed.set()

        return (
            lambda buffer_size: P.io_stage(make_watched_items, buffer_size=buffer_size),
            lambda: closed.wait(WAIT_LIMIT_TIME) and is_closed(),
            made,
        )

    def make_async_items(_: None) -> AsyncIterator[int]:
        agens.append(async_numbers())
        return agens[-1]

    return (
        lambda buffer_size: P.async_stage(make_async_items, buffer_size=buffer_size),
        lambda: len(agens) == 1 and inspect.getasyncgenstate(agens[0]) == inspect.AGEN_CLOSED,
        made,
    )


def test_a_stages_endless_generator_is_closed_on_failure(endless_stage: EndlessStage) -> None:
    endless, is_closed, _ = endless_stage

    async def run_and_check() -> bool:
        async with P.Pools.open(cpu_workers=1, io_workers=2) as pools:
            with run_error(ValueError, "^boom"):
                await outputs_of(endless(1) | P.io_stage(boom), [None], pools)
        return is_closed()  # checked before the event loop shuts down: it would close async generators itself

    assert asyncio.run(run_and_check())


def test_cancelling_a_run_stops_it_and_closes_the_generators(pools: P.Pools, endless_stage: EndlessStage) -> None:
    endless, is_closed, num_made = endless_stage
    in_flight = 2 + 10 + 1  # the two calls held, the queue between the two steps, one item waiting to be put
    release = threading.Event()
    ran_out: list[int] = []  # held calls not released by the test, but after `2 * WAIT_LIMIT_TIME`

    def held(item: int) -> list[int]:
        if not release.wait(2 * WAIT_LIMIT_TIME):  # longer than the cancel may take
            ran_out.append(item)
        return [item]

    async def cancel_once_blocked() -> tuple[int, bool]:
        """Cancels the run once the endless stage has made `in_flight` items and has had
        `SATURATION_GRACE_TIME` to make more."""
        run_task = asyncio.create_task(outputs_of(endless(10) | P.io_stage(held, concurrency=2), [None], pools))
        async with asyncio.timeout(WAIT_LIMIT_TIME):
            while num_made() < in_flight:
                await asyncio.sleep(0)  # lets the run go on
        await asyncio.sleep(SATURATION_GRACE_TIME)
        loop = asyncio.get_running_loop()
        assert isinstance(loop, TimerRecordingLoop)
        try:
            async with asyncio.timeout(WAIT_LIMIT_TIME):  # its own timer is scheduled before recording
                loop.recording = True
                run_task.cancel()
                # not `await run_task` in `pytest.raises(CancelledError)`: that would also catch the timeout's
                # cancellation; `asyncio.wait` without a timeout schedules no timer
                await asyncio.wait([run_task])
                loop.recording = False
        finally:
            release.set()  # only now: a cancel waiting for the held calls would not have finished
        assert run_task.cancelled()
        return len(asyncio.all_tasks()) - 1, is_closed()  # tasks left besides this one; checked inside the loop

    loop = TimerRecordingLoop()
    num_tasks_left, closed = asyncio.run(cancel_once_blocked(), loop_factory=lambda: loop)
    assert num_tasks_left == 0
    assert closed
    assert loop.delays == []  # the cancel waited for no time
    assert num_made() == in_flight  # the endless stage was blocked when cancelled and made nothing afterwards
    assert ran_out == []  # the cancel did not wait for the running pool tasks
