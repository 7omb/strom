"""Tests of `strom._stages.lifting`: lifted stages keep their settings and run only the focused element."""

from collections.abc import Callable

import helpers
from helpers import collect, inc, meaning, outputs_of, tracked_a
from hypothesis import given
from strategies import INPUTS, stages

import strom as P
from strom._stages.display import settings
from strom._stages.focus import Sequenced
from strom._stages.lifting import lift_first, lift_second, lift_sequenced


async def test_first_cpu_passes_unpicklable_element_through(process_pools: P.Pools) -> None:
    unpicklable = lambda: None  # noqa: E731
    lifted: P.Stage[tuple[int, Callable[[], None]], tuple[int, Callable[[], None]]] = P.first(P.cpu_stage(inc))
    outputs = await outputs_of(lifted, [(5, unpicklable)], process_pools)
    assert outputs[0][0] == 6
    assert outputs[0][1] is unpicklable


@given(stages(), INPUTS)
def test_second_mirrors_first(stage: P.Stage[int, int], items: list[int]) -> None:
    """second(f) = swap | first(f) | swap on the reference semantics: the mirrored lifting code agrees."""
    pairs = [(i, -i) for i in items]
    lifted_second: P.Stage[tuple[int, int], tuple[int, int]] = P.second(stage)
    lifted_first: P.Stage[tuple[int, int], tuple[int, int]] = P.first(stage)
    swapped: P.Stage[tuple[int, int], tuple[int, int]] = P.swap()
    assert meaning(lifted_second, pairs) == meaning(swapped | lifted_first | swapped, pairs)


@given(stages())
def test_lifting_keeps_every_setting(stage: P.Stage[int, int]) -> None:
    """Every lifting rebuilds the stage around other focuses: the settings of its steps, products, routes,
    gathers and loops (as the repr shows them) stay as they are."""

    def no_count(sequence: int, delta: int) -> None:
        return

    first: P.Stage[tuple[int, str], tuple[int, str]] = lift_first(stage)
    second: P.Stage[tuple[str, int], tuple[str, int]] = lift_second(stage)
    sequenced: P.Stage[Sequenced[int], Sequenced[int]] = lift_sequenced(stage, no_count)
    assert settings(first) == settings(second) == settings(sequenced) == settings(stage)


def test_lifted_steps_keep_their_concurrency() -> None:
    stage: P.Stage[tuple[int, int], tuple[int, int]] = P.first(
        P.io_stage(inc, concurrency=3) | P.io_stage(tracked_a, concurrency=2)
    )
    with helpers.TRACK.saturating({"a": 2}):
        collect(stage, [(i, i) for i in range(30)], io_workers=16)
    assert helpers.TRACK.num_max_active["a"] == 2
