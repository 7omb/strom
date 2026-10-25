"""Tests of `strom._interpreters.fusion`: groups of event-loop steps keep the meaning, run as one step,
let other tasks run, name themselves in errors and close what their members opened."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Generator

import pytest
from helpers import (
    FailingLines,
    add_pair,
    async_inc,
    at_most_three_lazily,
    bag,
    boom,
    collect,
    double,
    explode,
    inc,
    is_odd,
    many,
    meaning,
    neg,
    outputs_of,
    run_error,
    stats_of,
)
from hypothesis import given
from strategies import INPUTS, stages

import strom as P
from strom._closing import close_if_closable
from strom._interpreters.fusion import _SKIP_BUDGET, _fair, _focus_sync, fused
from strom._stages.focus import Focus
from strom._stages.model import DEFAULT_BUFFER_SIZE, AsyncExpand, Chain, Expand, Join, Step


def many_as_list(item: int) -> list[list[int]]:
    return [many(item)]  # ONE item: a list


def test_a_group_in_a_branch_drops_items() -> None:
    # the branch is one fused group, counted as a whole; its SKIPs never reach the join
    pairs = [(i, i) for i in range(6)]
    stage = P.product(P.stage(inc) | P.where(is_odd) | P.stage(neg), P.io_stage(neg))
    assert bag(collect(stage, pairs)) == bag([(-5, -4), (-3, -2), (-1, 0)])


@given(stages(), INPUTS)
def test_fusion_keeps_the_meaning(stage: P.Stage[int, int], items: list[int]) -> None:
    assert meaning(fused(stage), items) == meaning(stage, items)  # the same order too: groups run depth-first


def made_from_one_input[T](items: list[T]) -> P.Stage[None, T]:
    """A first member emitting `items` for its one input: the items of the group never come from a queue
    (whose emptying would give other tasks a turn)."""
    return P.stage(lambda _: items, name="items")


class CountedCalls:
    """User functions on the event loop that count their calls."""

    def __init__(self) -> None:
        self.num_calls = 0

    def neg(self, item: int) -> list[int]:
        self.num_calls += 1
        return [-item]

    def never(self, item: int) -> bool:
        self.num_calls += 1
        return False


NUM_STRETCH_ITEMS = 20 * _SKIP_BUDGET


DROPPING_STRETCH = _SKIP_BUDGET  # a group gives a turn after each budget of SKIPs


PUTTING_STRETCH = 2 * DEFAULT_BUFFER_SIZE + 1  # a full queue (both branch queues of a join) makes it wait


INPUTS_STRETCH = DEFAULT_BUFFER_SIZE  # a step takes at most the queue of the inputs before it waits for more


NUMBERS = list(range(NUM_STRETCH_ITEMS))
PAIRS = [(i, i) for i in NUMBERS]


type StretchRun = Callable[[CountedCalls, P.Pools], Awaitable[object]]
"""A run calling the functions of `CountedCalls`."""


def on_one_input(make_stage: Callable[[CountedCalls], P.Stage[None, object]]) -> StretchRun:
    """A run of the stage on one input: its first member emits the items."""
    return lambda calls, pools: outputs_of(make_stage(calls), [None], pools)


STRETCHES: dict[str, tuple[StretchRun, int]] = {
    "group puts": (on_one_input(lambda calls: made_from_one_input(NUMBERS) | P.stage(calls.neg)), PUTTING_STRETCH),
    "group drops": (
        on_one_input(lambda calls: made_from_one_input(NUMBERS) | P.where(calls.never)),
        DROPPING_STRETCH,
    ),
    "group after a pool step puts": (  # the fan-out of benchmarks/benchmark.py's test_streaming_fan_out
        on_one_input(
            lambda calls: (
                made_from_one_input([NUM_STRETCH_ITEMS]) | P.io_stage(many_as_list) | P.flatten() | P.stage(calls.neg)
            )
        ),
        PUTTING_STRETCH,
    ),
    "group after a pool step drops": (
        on_one_input(
            lambda calls: (
                made_from_one_input([NUM_STRETCH_ITEMS]) | P.io_stage(many_as_list) | P.flatten() | P.where(calls.never)
            )
        ),
        DROPPING_STRETCH,
    ),
    "lifted group drops": (
        on_one_input(lambda calls: made_from_one_input(PAIRS) | P.first(P.where(calls.never))),
        DROPPING_STRETCH,
    ),
    "join puts": (
        on_one_input(lambda calls: made_from_one_input(PAIRS) | P.product(P.stage(calls.neg), P.stage(calls.neg))),
        PUTTING_STRETCH,
    ),
    "join drops": (
        on_one_input(lambda calls: made_from_one_input(PAIRS) | P.product(P.where(calls.never), P.where(calls.never))),
        PUTTING_STRETCH,
    ),
    "inputs dropped": (  # the items come from the queue of the inputs, which the group empties
        lambda calls, pools: outputs_of(P.where(calls.never) | P.where(calls.never), range(NUM_STRETCH_ITEMS), pools),
        2 * INPUTS_STRETCH,  # two calls per item
    ),
}


@pytest.mark.parametrize("run, longest_allowed", list(STRETCHES.values()), ids=list(STRETCHES))
def test_runs_never_freeze_the_event_loop(run: StretchRun, longest_allowed: int) -> None:
    """The longest stretch of the user's calls between two turns of another task is bounded, whatever
    the number of items (a freeze growing with the items exceeds the bound 20-fold).

    Counts calls instead of measuring time (benchmarks/benchmark.py's `max_loop_freeze_ms`), so it does not
    depend on the machine."""
    calls = CountedCalls()

    async def longest_stretch() -> int:
        longest, running = 0, True

        async def other_task() -> None:
            nonlocal longest
            while running:
                calls.num_calls = 0
                await asyncio.sleep(0)  # one turn per pass of the event loop
                longest = max(longest, calls.num_calls)

        async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
            task = asyncio.create_task(other_task())
            await asyncio.sleep(0)  # lets it start
            await run(calls, pools)
            running = False
            await task
        return longest

    assert asyncio.run(longest_stretch()) <= longest_allowed


def lifted_explode() -> P.Stage[tuple[int, int], tuple[int, int]]:
    return P.first(P.stage(explode))


def explode_before_a_join() -> P.Stage[int, tuple[int, int]]:
    pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
    return P.stage(explode) | pairs | P.product(P.io_stage(inc), P.io_stage(neg))


@pytest.mark.parametrize(
    "run, notes",
    [
        (lambda: collect(P.stage(explode) | P.stage(inc), [1]), ["explode | inc"]),
        (lambda: collect(P.stage(inc) | P.stage(explode) | P.stage(neg), [1]), ["inc | explode | neg"]),
        (lambda: collect(lifted_explode() | P.stage(add_pair), [(1, 2)]), ["explode | add_pair"]),
        (lambda: collect(P.stage(at_most_three_lazily) | P.stage(boom), [3]), ["at_most_three_lazily | boom"]),
        (lambda: collect(explode_before_a_join(), [1]), ["explode | duplicate"]),
        (
            lambda: collect(P.product(P.io_stage(inc) | P.stage(explode), P.io_stage(neg)), [(1, 2)]),
            ["explode", "product(inc | explode, neg)"],
        ),
    ],
    ids=[
        "first member",
        "middle member",
        "lifted member",
        "while an earlier member iterates",
        "before a join",
        "in a branch",
    ],
)
def test_errors_in_a_group_name_the_group(run: Callable[[], object], notes: list[str]) -> None:
    with run_error(ValueError, r"^(boom|stage failed)\b") as info:
        run()
    assert info.value.exceptions[0].__notes__ == [f"in stage {note!r}" for note in notes]


@pytest.mark.parametrize("where", ["first member", "middle member", "lifted member"])
def test_groups_close_their_members_generators_on_failure(where: str) -> None:
    gens: list[Generator[object]] = []

    def numbers(item: int) -> Generator[int]:
        while True:
            yield item

    def pairs(item: int) -> Generator[tuple[int, int]]:
        while True:
            yield item, item

    def endless(item: int) -> Generator[int]:
        gen = numbers(item)
        gens.append(gen)
        return gen

    def endless_pairs(item: int) -> Generator[tuple[int, int]]:
        gen = pairs(item)
        gens.append(gen)
        return gen

    same: P.Stage[int, int] = P.identity()
    lifted: P.Stage[tuple[int, int], tuple[int, int]] = P.first(P.stage(endless))
    stages: dict[str, P.Stage[int, int]] = {  # on the input 1, each first emits 2: boom fails on it
        "first member": P.stage(endless) | P.stage(inc),
        "middle member": same | P.stage(endless) | P.stage(inc),
        "lifted member": P.stage(endless_pairs) | lifted | P.stage(add_pair),
    }

    async def run_and_check() -> list[str]:
        async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:
            with run_error(ValueError, "^boom"):
                await outputs_of(stages[where] | P.io_stage(boom), [1], pools)
        return [inspect.getgeneratorstate(g) for g in gens]  # checked in the running loop, references kept

    assert set(asyncio.run(run_and_check())) == {inspect.GEN_CLOSED}


def test_lifted_members_finish_their_inputs() -> None:
    # a member's focus finishes each input once, when it ends or is closed early (fusion meets no
    # focus with `finish` through the public API: counting is added after it)
    finished: list[int] = []

    def split(item: int) -> tuple[int, int]:
        return item, item

    def merge(b: int, kept: int) -> tuple[int, int]:
        return b, kept

    focus: Focus[int, tuple[int, int], int, int, int] = Focus(split, merge, finished.append)
    apply = _focus_sync(focus, range)
    assert list(apply(2)) == [(0, 2), (1, 2)]
    assert finished == [2]
    outputs = apply(3)
    assert next(outputs) == (0, 3)
    close_if_closable(outputs)  # stopped early
    assert finished == [2, 3]


def test_a_group_closes_its_iterator_when_stopped_early() -> None:
    lines = FailingLines()  # closable, not a generator: nothing else would close it

    async def run() -> None:
        outputs = _fair(lambda _: lines)(0)
        assert await anext(outputs) == 1
        await outputs.aclose()  # the run stopped early

    asyncio.run(run())
    assert lines.closed


def test_consecutive_event_loop_steps_run_as_one_step() -> None:
    to_pair: P.Stage[int, tuple[int, int]] = P.duplicate()
    outputs, stats = stats_of(
        P.stage(inc)
        | P.where(is_odd)
        | P.io_stage(double, concurrency=2)
        | to_pair
        | P.first(P.stage(neg))
        | P.stage(add_pair),
        range(6),
    )
    assert outputs == [0, 0, 0]  # 1, 3, 5 -> doubled -> paired with their negation
    # a group is one step occurrence, named by its chain, with one position
    assert [(str(s.step_id), s.step_id.concurrency, s.num_items_in, s.num_items_out) for s in stats.step_stats] == [
        ("1:inc | is_odd", 1, 6, 3),
        ("2:double", 2, 3, 3),
        ("3:duplicate | neg | add_pair", 1, 3, 3),
    ]


def test_fusion_keeps_steps_that_wait_and_joins_apart() -> None:
    def make() -> P.Stage[int, int]:
        pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
        return (
            P.stage(neg)
            | pairs
            | P.product(P.stage(inc) | P.stage(neg), P.io_stage(inc))
            | P.stage(add_pair)
            | P.async_stage(async_inc)
            | P.stage(neg)
        )

    fused_stage = fused(make())
    assert isinstance(fused_stage, Chain)
    assert isinstance(fused_stage.head, Step)
    assert fused_stage.head.name == "neg | duplicate"  # the group before the join
    join = fused_stage.tail
    assert isinstance(join, Chain)
    assert isinstance(join.head, Join)
    left, right = join.head.left, join.head.right
    assert isinstance(left, Step)
    assert isinstance(left.leaf, AsyncExpand)
    assert left.name == "inc | neg"
    assert isinstance(right, Step)
    assert isinstance(right.leaf, Expand)
    assert meaning(fused_stage, [3]) == meaning(make(), [3])
