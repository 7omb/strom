"""Tests of the generated pipelines of `strategies`: the bounds of their outputs per input, and the leaves and
the record of the hash pipelines."""

from contextlib import suppress

import pytest
from helpers import Failure, at_most_three, collect_inline, meaning
from hypothesis import given
from strategies import (
    HASH_INPUTS,
    LEAF_KINDS,
    MAX_OUTPUTS,
    Bounded,
    FanOut,
    HashLeaf,
    chain_of,
    first_of,
    gather_of,
    hash_leaf,
    hash_maps,
    hash_stages,
    loop_of,
    mix,
    product_of,
    recorded,
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


# ---- hash pipelines
def outcome(stage: P.Stage[int, int], item: int) -> str:
    """The outputs of `stage` for `item`, or its failure."""
    try:
        return repr(sorted(meaning(stage, [item])))
    except ExceptionGroup as failed:
        return repr(failed.exceptions)


@pytest.mark.parametrize("fan_out", ["one", "some", "keep", "fail"])
def test_a_hash_leaf_gives_the_same_items_in_every_kind(fan_out: FanOut) -> None:
    by_kind = {
        kind: [outcome(hash_leaf(7, fan_out, kind, concurrency=2, buffer_size=1).stage, item) for item in range(64)]
        for kind in LEAF_KINDS
    }
    assert all(outcomes == by_kind["loop"] for outcomes in by_kind.values())
    assert len(set(by_kind["loop"])) > 2  # the items differ: a hash of each


def test_the_fan_outs_of_a_hash_leaf() -> None:
    num_outputs = {
        fan_out: {len(HashLeaf(0, 7, fan_out, 1).outputs(item)) for item in range(64) if mix(item, 7) % 16}
        for fan_out in ("one", "some", "keep", "fail")
    }
    assert num_outputs == {"one": {1}, "some": {0, 1, 2, 3}, "keep": {0, 1}, "fail": {1}}
    failing = [item for item in range(64) if mix(item, 7) % 16 == 0]
    assert failing
    with pytest.raises(Failure):
        HashLeaf(0, 7, "fail", 1).outputs(failing[0])


@given(hash_stages())
def test_generated_hash_stages_keep_the_bound_of_outputs(stage: P.Stage[int, int]) -> None:
    for item in range(16):
        with suppress(ExceptionGroup):  # a failing leaf
            assert len(meaning(stage, [item])) <= MAX_OUTPUTS


@given(hash_maps(), HASH_INPUTS)
def test_hash_maps_give_one_output_per_input(stage: P.Stage[int, int], items: list[int]) -> None:
    assert len(meaning(stage, items)) == len(items)


@given(hash_stages(failing=False), HASH_INPUTS)
def test_hash_stages_without_failing_leaves_do_not_fail(stage: P.Stage[int, int], items: list[int]) -> None:
    meaning(stage, items)


@given(hash_stages(ordered=True, failing=False), HASH_INPUTS)
def test_ordered_hash_stages_give_the_reference_order_on_the_inline_backend(
    stage: P.Stage[int, int], items: list[int]
) -> None:
    assert collect_inline(stage, items) == meaning(stage, items)


def test_calls_count_by_leaf_and_input_and_the_calls_above_the_concurrency() -> None:
    one_at_a_time, two_at_a_time = HashLeaf(0, 7, "one", concurrency=1), HashLeaf(1, 7, "one", concurrency=2)
    with recorded() as calls:
        for leaf in (one_at_a_time, two_at_a_time):
            with calls.call(leaf, 10), calls.call(leaf, 11):  # two calls at one time
                pass
            with calls.call(leaf, 10):
                pass
    assert calls.counts == {(0, 10): 2, (0, 11): 1, (1, 10): 2, (1, 11): 1}
    assert calls.num_above_limit == 1  # the second call of the leaf with a concurrency of 1


def test_a_leaf_records_into_the_calls_of_its_block() -> None:
    leaf = HashLeaf(0, 7, "some", concurrency=1)
    with recorded() as outer:
        leaf.on_loop(1)
        with recorded() as inner:
            list(leaf.lazily(2))
        leaf.in_pool(3)
    assert sorted(outer.counts) == [(0, 1), (0, 3)]
    assert sorted(inner.counts) == [(0, 2)]
