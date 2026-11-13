"""Tests of the generated pipelines of `strategies`: the bounds of their outputs per input."""

import pytest
from helpers import at_most_three, meaning
from hypothesis import given
from strategies import (
    MAX_OUTPUTS,
    Bounded,
    chain_of,
    first_of,
    gather_of,
    loop_of,
    product_of,
    route_of,
    second_of,
    stages,
)

import strom as P


def most_outputs(stage: P.Stage[int, int]) -> int:
    # every input: a stage reaches its bound on a few only (`at_most_three` emits three for 3 mod 4)
    return max(len(meaning(stage, [item])) for item in range(-20, 21))


ONE_TO_THREE = Bounded(P.stage(at_most_three), 3)
PAIRS = product_of(ONE_TO_THREE, ONE_TO_THREE, buffer_size=1)


# each case gives more outputs than a wrong rule would allow (the larger bound for a product or a chain, the
# smaller for a route, the loop's without the second application)
@pytest.mark.parametrize(
    ("bounded", "expected"),
    [
        (PAIRS, 9),
        (chain_of(PAIRS, ONE_TO_THREE), 14),
        (first_of(PAIRS), 9),
        (second_of(PAIRS), 9),
        (route_of(PAIRS, ONE_TO_THREE, buffer_size=1), 9),
        (gather_of(PAIRS, concurrency=1, buffer_size=1), 1),
        (loop_of(PAIRS, concurrency=1, buffer_size=1), 32),
    ],
    ids=["product", "chain", "first", "second", "route", "gather", "loop"],
)
def test_bounds_cover_the_outputs_of_each_combination(bounded: Bounded, expected: int) -> None:
    assert most_outputs(bounded.stage) == expected <= bounded.max_outputs


@given(stages())
def test_generated_stages_keep_the_bound_of_outputs(stage: P.Stage[int, int]) -> None:
    assert most_outputs(stage) <= MAX_OUTPUTS
