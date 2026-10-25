"""Tests of `strom._stages.factories`: stages in every placement, their names, concurrency and buffer
sizes."""

import asyncio
import functools
from collections import Counter
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import pytest
from helpers import (
    async_at_most_three,
    async_inc,
    at_most_three,
    at_most_three_lazily,
    bag,
    collect,
    inc,
    is_odd,
    meaning_async,
    neg,
    outputs_of,
)

import strom as P
from strom._stages.model import Step
from strom.metrics import Event, TaskFinished


def nothing(item: int) -> list[int]:  # module-level: runs in a worker process
    return []


async def async_nothing(item: int) -> AsyncIterator[int]:
    await asyncio.sleep(0)
    return
    yield  # an async generator that yields nothing


def odd_numbers_below(item: int) -> Iterator[int]:
    return (i for i in range(item) if i % 2 == 1)


def test_stages_flatten_and_filter() -> None:
    assert sorted(collect(P.stage(odd_numbers_below), [3, 6])) == [1, 1, 3, 5]
    unpacked: P.Stage[tuple[int, ...], int] = P.flatten()  # annotated: nothing else binds its T
    assert collect(unpacked, [(1, 2), (), (3,)]) == [1, 2, 3]  # any iterable
    letters: P.Stage[str, str] = P.flatten()
    assert collect(letters, ["ab"]) == ["a", "b"]
    assert collect(P.where(is_odd), range(6)) == [1, 3, 5]


def test_each_input_creates_its_own_iterable() -> None:
    created: list[int] = []

    def numbers(_: None) -> Iterator[int]:
        created.append(1)
        return iter([1, 2])

    assert collect(P.stage(numbers), [None, None]) == [1, 2, 1, 2]
    assert len(created) == 2


def append_to(path: Path, text: str) -> list[str]:  # module-level: runs in a worker process
    with path.open("a", encoding="utf-8") as f:
        f.write(text)
    return []  # an effect only


async def test_factory_matrix_on_all_pools(process_pools: P.Pools, tmp_path: Path) -> None:
    """Every placement of stages (one, several and no outputs) agrees with the reference semantics,
    including the process backend (picklable functions). Chains of placements: the Hypothesis tests."""
    stages: dict[str, P.Stage[int, int]] = {
        "stage(inc)": P.stage(inc),
        "async_stage(async_inc)": P.async_stage(async_inc),
        "io_stage(inc)": P.io_stage(inc),
        "cpu_stage(inc)": P.cpu_stage(inc),
        "stage(at_most_three)": P.stage(at_most_three),
        "async_stage(async_at_most_three)": P.async_stage(async_at_most_three),
        "io_stage(at_most_three_lazily)": P.io_stage(at_most_three_lazily),
        "cpu_stage(at_most_three_lazily)": P.cpu_stage(at_most_three_lazily),
    }
    for stage_label, stage in stages.items():
        outputs = await outputs_of(stage, [1, 2, 3], process_pools)
        assert bag(outputs) == bag(await meaning_async(stage, [1, 2, 3])) != Counter(), stage_label
    emitting_nothing: dict[str, P.Stage[int, int]] = {
        "stage": P.stage(nothing),
        "async_stage": P.async_stage(async_nothing),
        "io_stage": P.io_stage(nothing),
        "cpu_stage": P.cpu_stage(nothing),
    }
    for label, stage in emitting_nothing.items():
        assert await outputs_of(stage, [1, 2, 3], process_pools) == [], label
    path = tmp_path / "effect.txt"
    await outputs_of(P.cpu_stage(functools.partial(append_to, path)), ["x"], process_pools)  # the effect happens
    assert path.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize(
    "make_stage",
    [
        lambda: P.async_stage(async_inc, concurrency=3),
        lambda: P.io_stage(inc, concurrency=3),
        lambda: P.cpu_stage(inc, concurrency=3),
    ],
    ids=["async_stage", "io_stage", "cpu_stage"],
)
async def test_factories_start_as_many_tasks_as_their_concurrency(
    make_stage: Callable[[], P.Stage[int, object]],
) -> None:
    stage = make_stage()
    events: list[Event] = []
    async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:
        await outputs_of(stage, range(6), pools, recorder=events.append)
    assert sum(isinstance(e, TaskFinished) and e.step_id.name == stage.name for e in events) == 3


@pytest.mark.parametrize(
    "make_stage",
    [
        lambda: P.async_stage(async_inc, buffer_size=3),
        lambda: P.io_stage(inc, buffer_size=3),
        lambda: P.cpu_stage(inc, buffer_size=3),
    ],
    ids=["async_stage", "io_stage", "cpu_stage"],
)
def test_factories_pass_on_their_buffer_size(make_stage: Callable[[], P.Stage[int, int]]) -> None:
    stage = make_stage()
    assert isinstance(stage, Step)
    assert stage.buffer_size == 3


def test_stage_names() -> None:
    assert P.io_stage(inc).name == "inc"
    assert P.stage(odd_numbers_below).name == "odd_numbers_below"
    assert P.io_stage(functools.partial(inc)).name == "stage"  # objects without a name
    assert P.io_stage(inc, name="custom").name == "custom"
    assert P.product(P.stage(inc), P.stage(neg)).name == "product(inc, neg)"


def test_pair_and_tag_plumbing() -> None:
    pairs = [(1, "a"), (2, "b")]
    swapped: P.Stage[tuple[int, str], tuple[str, int]] = P.swap()
    firsts: P.Stage[tuple[int, str], int] = P.fst()
    seconds: P.Stage[tuple[int, str], str] = P.snd()
    assert collect(swapped, pairs) == [("a", 1), ("b", 2)]
    assert collect(firsts, pairs) == [1, 2]
    assert collect(seconds, pairs) == ["a", "b"]
    routed = P.tag_by(is_odd) | P.route(P.stage(inc), P.stage(neg)) | P.untag()
    assert sorted(collect(routed, [1, 2, 3])) == [-2, 2, 4]  # odd: inc, even: neg
