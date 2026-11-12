"""Tests of `strom._stages.combinators`: their semantics with expected values, and their laws on the
reference semantics and in runs (arrows, the monoidal product `product`, ArrowChoice, `gather`, `loop`)."""

import asyncio
import functools
from collections.abc import Awaitable, Callable
from typing import NamedTuple

import helpers
import pytest
from helpers import (
    Countdown,
    Pickling,
    Tagged,
    at_most_three,
    bag,
    collect,
    countdown_body,
    countdown_from,
    double,
    inc,
    is_odd,
    many,
    meaning,
    neg,
    outputs_of,
    repeat,
    tagged_items,
    tagged_pairs,
    text,
    to_right,
    tracked_a,
    tracked_b,
    with_depth,
)
from hypothesis import given, settings
from strategies import INPUTS, NONEMPTY_INPUTS, stages

import strom as P


def assoc_right(nested: tuple[tuple[int, int], int]) -> list[tuple[int, tuple[int, int]]]:
    (a, b), c = nested
    return [(a, (b, c))]


def assoc_left(nested: tuple[int, tuple[int, int]]) -> list[tuple[tuple[int, int], int]]:
    a, (b, c) = nested
    return [((a, b), c)]


swap_tagged: P.Stage[tuple[Tagged, int], tuple[int, Tagged]] = P.swap()


def to_left(item: int) -> list[P.Left[int]]:
    return [P.Left(item)]


def on_left(fn: Callable[[int], list[int]], item: Tagged) -> list[Tagged]:
    """fn on `Left` items in one plain function (not lifted by `left`); `Right` items pass."""
    match item:
        case P.Left(value):
            return [P.Left(out) for out in fn(value)]
        case P.Right():
            return [item]


def on_right(fn: Callable[[int], list[int]], item: Tagged) -> list[Tagged]:
    """Mirror image of `on_left`."""
    match item:
        case P.Left():
            return [item]
        case P.Right(value):
            return [P.Right(out) for out in fn(value)]


type NestedSum = P.Left[Tagged] | P.Right[int]


def nested_sums(items: list[int]) -> list[NestedSum]:
    """Each item in one of the three positions of a nested sum, by its remainder modulo 3."""

    def nested(item: int) -> NestedSum:
        match item % 3:
            case 0:
                return P.Left(P.Left(item))
            case 1:
                return P.Left(P.Right(item))
            case _:
                return P.Right(item)

    return [nested(item) for item in items]


def assoc_sum(item: NestedSum) -> list[P.Left[int] | P.Right[Tagged]]:
    """Left(Left(a)) -> Left(a), Left(Right(b)) -> Right(Left(b)), Right(c) -> Right(Right(c))."""
    match item:  # type: ignore[exhaustive-match]  # pyright: ignore[reportMatchNotExhaustive]
        case P.Left(P.Left(a)):
            return [P.Left(a)]
        case P.Left(P.Right(b)):
            return [P.Right(P.Left(b))]
        case P.Right(c):
            return [P.Right(P.Right(c))]
    raise AssertionError(item)  # unreachable: none of mypy, pyright and ty narrows nested class patterns


def dist_sum(pair: tuple[Tagged, int]) -> list[P.Left[tuple[int, int]] | P.Right[tuple[int, int]]]:
    """(Left(a), x) -> Left((a, x)), (Right(c), x) -> Right((c, x))."""
    match pair[0]:
        case P.Left(a):
            return [P.Left((a, pair[1]))]
        case P.Right(c):
            return [P.Right((c, pair[1]))]


def undist_sum(item: P.Left[tuple[int, int]] | P.Right[tuple[int, int]]) -> list[tuple[Tagged, int]]:
    """Inverse of `dist_sum`."""
    match item:
        case P.Left((a, x)):
            return [(P.Left(a), x)]
        case P.Right((c, x)):
            return [(P.Right(c), x)]


def sorted_list(items: list[int]) -> list[list[int]]:
    return [sorted(items)]


def singleton(item: int) -> list[list[int]]:
    return [[item]]


def paths(path: str) -> list[P.Left[str] | P.Right[str]]:
    """Emits the path and feeds back its two extensions up to length 2: a tree, iterated."""
    extensions: list[P.Left[str] | P.Right[str]] = [P.Left(path + "a"), P.Left(path + "b")] if len(path) < 2 else []
    return [P.Right(path), *extensions]


first_of_countdown: P.Stage[tuple[Countdown, int], Countdown] = P.fst()
swap_countdown: P.Stage[tuple[Countdown, int], tuple[int, Countdown]] = P.swap()


ARROWS: list[tuple[P.Stage[int, int], Callable[[int], list[int]]]] = [
    (P.stage(inc), inc),
    (P.io_stage(double, concurrency=2), double),
    (P.cpu_stage(neg, concurrency=2), neg),
]
"""A 1:1 function as a stage in each placement, with the function itself (`arr fn` in the arrow laws)."""


def on_first(fn: Callable[[int], list[int]], pair: tuple[int, int]) -> list[tuple[int, int]]:
    """fn on the first element of `pair` in one plain function (not lifted by `first`)."""
    return [(out, pair[1]) for out in fn(pair[0])]


# ------------------------------------------------------- semantics with expected values
def test_first_and_second_product_semantics() -> None:
    kept: P.Stage[tuple[int, str], tuple[int, str]] = P.first(P.where(is_odd))
    assert sorted(collect(kept, [(1, "a"), (2, "b"), (3, "c")])) == [(1, "a"), (3, "c")]  # 0 outputs: pair dropped
    unpacked: P.Stage[tuple[list[int], str], tuple[int, str]] = P.first(P.flatten())
    outputs = collect(unpacked, [([1, 2], "x"), ([], "y")])
    assert sorted(outputs) == [(1, "x"), (2, "x")]  # n outputs: n pairs
    negated: P.Stage[tuple[str, int], tuple[str, int]] = P.second(P.stage(neg))
    assert collect(negated, [("k", 1)]) == [("k", -1)]
    duplicated: P.Stage[int, tuple[int, int]] = P.duplicate()
    assert collect(duplicated, [7]) == [(7, 7)]


def test_product_pairs_the_results_of_both_branches() -> None:
    outputs = collect(P.product(P.io_stage(many), P.stage(many)), [(2, 3), (0, 1), (3, 0)])
    assert bag(outputs) == bag([(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)])  # 2 x 3; none if a branch emits none
    duplicated: P.Stage[int, tuple[int, int]] = P.duplicate()
    outputs = collect(duplicated | P.product(P.io_stage(tracked_a), P.io_stage(tracked_b)), [1, 2])
    assert sorted(outputs) == [(1, 1), (2, 2)]
    assert (helpers.TRACK.num_calls["a"], helpers.TRACK.num_calls["b"]) == (2, 2)  # each branch once per input


def test_reordering_lifted_stages_keeps_the_outputs_not_the_calls() -> None:
    """Laws of stages equate outputs (as bags), not calls (`test_first_and_second_commute` checks the
    outputs)."""

    def three_tracked_a(item: int) -> list[int]:
        return [helpers.TRACK.run("a", item)] * 3

    pairs = [(1, 2), (3, 4)]
    f: P.Stage[tuple[int, int], tuple[int, int]] = P.first(P.stage(three_tracked_a))
    g: P.Stage[tuple[int, int], tuple[int, int]] = P.second(P.io_stage(tracked_b))
    f_then_g = collect(f | g, pairs)
    assert (helpers.TRACK.num_calls["a"], helpers.TRACK.num_calls["b"]) == (2, 6)  # g once per output of f
    helpers.TRACK.num_calls.clear()
    g_then_f = collect(g | f, pairs)
    assert (helpers.TRACK.num_calls["a"], helpers.TRACK.num_calls["b"]) == (2, 2)  # g once per input
    assert bag(f_then_g) == bag(g_then_f)


def test_route_sends_each_input_to_one_branch() -> None:
    outputs = collect(P.route(P.io_stage(tracked_a), P.io_stage(tracked_b)), tagged_items())
    assert bag(outputs) == bag([P.Left(1), P.Right(2), P.Left(3)])
    assert (helpers.TRACK.num_calls["a"], helpers.TRACK.num_calls["b"]) == (2, 1)  # each input in its branch only
    outputs = collect(P.route(P.io_stage(many), P.where(is_odd)), tagged_items())
    assert bag(outputs) == bag([P.Left(0), P.Left(0), P.Left(1), P.Left(2)])  # 1:0..n, the Right dropped


def test_tag_by_left_and_right() -> None:
    tagged = P.tag_by(is_odd)
    assert bag(collect(tagged, [1, 2, 3])) == bag([P.Left(1), P.Right(2), P.Left(3)])
    assert bag(collect(tagged | P.left(P.io_stage(neg)), [1, 2, 3])) == bag([P.Left(-1), P.Right(2), P.Left(-3)])
    assert bag(collect(tagged | P.right(P.io_stage(neg)), [1, 2, 3])) == bag([P.Left(1), P.Right(-2), P.Left(3)])


def test_lifted_route_and_route_in_a_product_branch() -> None:
    route = P.route(P.io_stage(neg), P.stage(functools.partial(repeat, times=2)))
    lifted: P.Stage[tuple[Tagged, int], tuple[Tagged, int]] = P.first(route)
    assert bag(collect(lifted, tagged_pairs())) == bag([(P.Left(-2), 0), (P.Right(2), 0), (P.Right(2), 0)])
    mirrored: P.Stage[tuple[int, Tagged], tuple[int, Tagged]] = P.second(route)
    assert bag(collect(swap_tagged | mirrored, tagged_pairs())) == bag(
        [(0, P.Left(-2)), (0, P.Right(2)), (0, P.Right(2))]
    )
    in_branch = P.product(route, P.io_stage(text))  # the branch counts the route's items
    assert bag(collect(in_branch, tagged_pairs())) == bag([(P.Left(-2), "0"), (P.Right(2), "0"), (P.Right(2), "0")])


def test_gather_emits_the_outputs_of_each_input_as_one_list() -> None:
    stage = P.gather(P.io_stage(many) | P.where(is_odd)) | P.stage(sorted_list)
    assert stage.name == "gather(many | is_odd) | sorted_list"
    assert bag(collect(stage, [4, 0, 2])) == bag([[1, 3], [], [1]])  # [] for no outputs
    assert bag(collect(P.gather(P.stage(inc)), [2, 3])) == bag([[3], [4]])


def test_loop_feeds_left_outputs_back() -> None:
    looped = P.loop(P.io_stage(countdown_from))
    assert looped.name == "loop(countdown_from)"
    assert bag(collect(looped, [2, 0])) == bag([2, 1, 0, 0])
    assert meaning(looped, [2, 0]) == [2, 1, 0, 0]
    tree = P.loop(P.stage(paths))
    assert meaning(tree, [""]) == ["", "a", "aa", "ab", "b", "ba", "bb"]  # depth-first (pre-order)
    assert bag(collect(tree, [""])) == bag(meaning(tree, [""]))
    assert bag(collect(P.loop(P.stage(to_right)), [5, 6])) == bag([5, 6])  # no feedback


def test_lifted_gather_and_loop_and_in_a_product_branch() -> None:
    gathered: P.Stage[int, list[int]] = P.gather(P.io_stage(many)) | P.stage(sorted_list)
    looped: P.Stage[int, int] = P.loop(P.io_stage(countdown_from))
    lifted_gather: P.Stage[tuple[int, str], tuple[list[int], str]] = P.first(gathered)
    assert bag(collect(lifted_gather, [(2, "x"), (0, "y")])) == bag([([0, 1], "x"), ([], "y")])
    mirrored_loop: P.Stage[tuple[str, int], tuple[str, int]] = P.second(looped)
    assert bag(collect(mirrored_loop, [("x", 1)])) == bag([("x", 1), ("x", 0)])
    in_branches = P.product(looped, gathered)  # each branch counts the items of the gather or loop
    assert bag(collect(in_branches, [(1, 2)])) == bag([(1, [0, 1]), (0, [0, 1])])


type Nested = tuple[tuple[str, tuple[tuple[int, int], int]], str]


def test_nested_product_first_and_second() -> None:
    inner = P.product(P.stage(neg), P.io_stage(functools.partial(repeat, times=2)))
    assert collect(P.product(P.stage(text), inner), [(1, (2, 3))]) == [("1", (-2, 3))] * 2
    stage: P.Stage[Nested, Nested] = P.first(
        P.second(P.product(P.product(P.stage(neg), P.stage(inc)), P.stage(double)))
    )
    assert collect(stage, [(("x", ((1, 2), 3)), "y")]) == [(("x", ((-1, 3), 6)), "y")]


# ------------------------------------------------------------------- laws, with Hypothesis
class LawSides(NamedTuple):
    """Both sides of a law, applied to the same inputs: their meanings and their outputs in a run, as
    functions, so that the type of the inputs, different from law to law, stays inside (`law_sides`)."""

    meanings: Callable[[], tuple[list[object], list[object]]]
    runs: Callable[[P.Pools], Awaitable[tuple[list[object], list[object]]]]


def law_sides[I](inputs: list[I], left: P.Stage[I, object], right: P.Stage[I, object]) -> LawSides:
    async def runs(pools: P.Pools) -> tuple[list[object], list[object]]:
        return await outputs_of(left, inputs, pools), await outputs_of(right, inputs, pools)

    return LawSides(lambda: (meaning(left, inputs), meaning(right, inputs)), runs)


def check_meanings(sides: LawSides) -> None:
    left, right = sides.meanings()
    assert bag(left) == bag(right)


def check_runs(sides: LawSides, without_shared_memory: bool = False) -> None:
    """Runs both sides in an event loop of their own (the Hypothesis tests are sync); without shared memory
    on `PicklingBackend`s, then no worker may keep an iterator."""
    cpu, io = Pickling(), Pickling()

    async def run() -> tuple[list[object], list[object]]:
        opened = (
            P.Pools.open_on(cpu=cpu, io=io)
            if without_shared_memory
            else P.Pools.open(cpu_workers=2, io_workers=8, cpu_backend="thread")
        )
        async with opened as pools:
            return await sides.runs(pools)

    left, right = asyncio.run(run())
    assert bag(left) == bag(right) == bag(sides.meanings()[0])
    assert cpu.num_registered() == io.num_registered() == 0


def pairs_of(items: list[int]) -> list[tuple[int, int]]:
    return [(i, -i) for i in items]


def nested_pairs_of(items: list[int]) -> list[tuple[tuple[int, int], int]]:
    return [((i, -i), 2 * i) for i in items]


def tagged_by_parity(item: int) -> Tagged:
    """What `tag_by(is_odd)` emits for `item`."""
    return P.Left(item) if is_odd(item) else P.Right(item)


@given(stages(), stages(), stages(), INPUTS)
def test_composition_laws(a: P.Stage[int, int], b: P.Stage[int, int], c: P.Stage[int, int], items: list[int]) -> None:
    assert meaning((a | b) | c, items) == meaning(a | (b | c), items)  # associativity
    same: P.Stage[int, int] = P.identity()
    assert meaning(same | a, items) == meaning(a, items) == meaning(a | same, items)
    pairs = pairs_of(items)
    first_a_b: P.Stage[tuple[int, int], tuple[int, int]] = P.first(a | b)
    first_a: P.Stage[tuple[int, int], tuple[int, int]] = P.first(a)
    second_a_b: P.Stage[tuple[int, int], tuple[int, int]] = P.second(a | b)
    second_a: P.Stage[tuple[int, int], tuple[int, int]] = P.second(a)
    assert bag(meaning(first_a_b, pairs)) == bag(meaning(first_a | P.first(b), pairs))
    assert bag(meaning(second_a_b, pairs)) == bag(meaning(second_a | P.second(b), pairs))


def product_law_sides(
    f: P.Stage[int, int], g: P.Stage[int, int], h: P.Stage[int, int], items: list[int]
) -> dict[str, LawSides]:
    """Both sides of each law of `product` as the monoidal product (a bifunctor, symmetric and
    associative) of the category of stages, applied to the same inputs, by law."""
    pairs, nested = pairs_of(items), nested_pairs_of(items)
    swapped: P.Stage[tuple[int, int], tuple[int, int]] = P.swap()
    to_right: P.Stage[tuple[tuple[int, int], int], tuple[int, tuple[int, int]]] = P.stage(assoc_right)
    to_left: P.Stage[tuple[int, tuple[int, int]], tuple[tuple[int, int], int]] = P.stage(assoc_left)
    first_f: P.Stage[tuple[int, int], tuple[int, int]] = P.first(f)
    with_identity: P.Stage[tuple[int, int], tuple[int, int]] = P.product(f, P.identity())
    return {
        "product_is_first_then_second": law_sides(pairs, P.product(f, g), first_f | P.second(g)),
        "first_is_product_with_identity": law_sides(pairs, first_f, with_identity),
        "interchange": law_sides(pairs, P.product(f, g) | P.product(g, h), P.product(f | g, g | h)),
        "symmetry": law_sides(pairs, swapped | P.product(f, g) | swapped, P.product(g, f)),
        "associativity": law_sides(
            nested, P.product(P.product(f, g), h), to_right | P.product(f, P.product(g, h)) | to_left
        ),
    }


PRODUCT_LAWS = list(product_law_sides(P.identity(), P.identity(), P.identity(), []))


@pytest.mark.parametrize("law", PRODUCT_LAWS)
@given(stages(), stages(), stages(), INPUTS)
def test_product_laws(
    law: str, f: P.Stage[int, int], g: P.Stage[int, int], h: P.Stage[int, int], items: list[int]
) -> None:
    check_meanings(product_law_sides(f, g, h, items)[law])


@pytest.mark.parametrize("law", PRODUCT_LAWS)
@given(stages(), stages(), stages(), NONEMPTY_INPUTS)
def test_runs_satisfy_product_laws(
    law: str, f: P.Stage[int, int], g: P.Stage[int, int], h: P.Stage[int, int], items: list[int]
) -> None:
    check_runs(product_law_sides(f, g, h, items)[law])


@pytest.mark.parametrize("law", PRODUCT_LAWS)
@settings(max_examples=15)
@given(stages(), stages(), stages(), NONEMPTY_INPUTS)
def test_runs_without_shared_memory_satisfy_product_laws(
    law: str, f: P.Stage[int, int], g: P.Stage[int, int], h: P.Stage[int, int], items: list[int]
) -> None:
    check_runs(product_law_sides(f, g, h, items)[law], without_shared_memory=True)


@given(stages(), stages(), INPUTS)
def test_first_and_second_commute(a: P.Stage[int, int], b: P.Stage[int, int], items: list[int]) -> None:
    """Runs promise a bag, so lifted stages on different elements can be reordered: the outputs stay the
    same, the calls do not (`test_reordering_lifted_stages_keeps_the_outputs_not_the_calls`)."""
    first_a: P.Stage[tuple[int, int], tuple[int, int]] = P.first(a)
    second_b: P.Stage[tuple[int, int], tuple[int, int]] = P.second(b)
    check_meanings(law_sides(pairs_of(items), first_a | second_b, second_b | first_a))


def arrow_law_sides(f: P.Stage[int, int], items: list[int]) -> dict[str, LawSides]:
    """Both sides of the arrow laws of `first` (Hughes 2000) that compare lifted with unlifted or singly
    lifted stages, applied to the same inputs, by law."""
    pairs, nested = pairs_of(items), nested_pairs_of(items)
    lifted: P.Stage[tuple[int, int], tuple[int, int]] = P.first(f)
    lifted_twice: P.Stage[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = P.first(P.first(f))
    lifted_nested: P.Stage[tuple[int, tuple[int, int]], tuple[int, tuple[int, int]]] = P.first(f)
    to_first: P.Stage[tuple[int, int], int] = P.fst()
    to_right: P.Stage[tuple[tuple[int, int], int], tuple[int, tuple[int, int]]] = P.stage(assoc_right)
    arrows: list[tuple[str, P.Stage[tuple[int, int], tuple[int, int]], P.Stage[tuple[int, int], tuple[int, int]]]] = [
        (arrow.name, P.first(arrow), P.stage(functools.partial(on_first, fn))) for arrow, fn in ARROWS
    ]
    return {
        "first_then_fst": law_sides(pairs, lifted | to_first, to_first | f),  # first f >>> arr fst = arr fst >>> f
        # first (first f) >>> arr assoc = arr assoc >>> first f
        "first_first_then_assoc": law_sides(nested, lifted_twice | to_right, to_right | lifted_nested),
        **{
            f"first_arr_{name}": law_sides(pairs, left, right) for name, left, right in arrows
        },  # first (arr f) = arr (first f)
    }


ARROW_LAWS = list(arrow_law_sides(P.identity(), []))


@pytest.mark.parametrize("law", ARROW_LAWS)
@given(stages(), INPUTS)
def test_arrow_laws(law: str, f: P.Stage[int, int], items: list[int]) -> None:
    check_meanings(arrow_law_sides(f, items)[law])


@pytest.mark.parametrize("law", ARROW_LAWS)
@given(stages(), NONEMPTY_INPUTS)
def test_runs_satisfy_arrow_laws(law: str, f: P.Stage[int, int], items: list[int]) -> None:
    check_runs(arrow_law_sides(f, items)[law])


def choice_law_sides(f: P.Stage[int, int], g: P.Stage[int, int], items: list[int]) -> dict[str, LawSides]:
    """Both sides of the ArrowChoice laws of `left` (Hughes 2000), the definition of `route` by `left` and
    `right`, and the distributivity that lifting a route uses, applied to the same inputs, by law."""
    tagged = [tagged_by_parity(item) for item in items]
    nested = nested_sums(items)
    pairs = [(tagged_by_parity(item), -item) for item in items]
    left_f: P.Stage[Tagged, Tagged] = P.left(f)
    left_g: P.Stage[Tagged, Tagged] = P.left(g)
    left_f_g: P.Stage[Tagged, Tagged] = P.left(f | g)
    left_left_f: P.Stage[NestedSum, P.Left[Tagged] | P.Right[int]] = P.left(P.left(f))
    left_f_nested: P.Stage[P.Left[int] | P.Right[Tagged], P.Left[int] | P.Right[Tagged]] = P.left(f)
    right_g: P.Stage[Tagged, Tagged] = P.right(g)
    lifted_route: P.Stage[tuple[Tagged, int], tuple[Tagged, int]] = P.first(P.route(f, g))
    first_f: P.Stage[tuple[int, int], tuple[int, int]] = P.first(f)
    first_g: P.Stage[tuple[int, int], tuple[int, int]] = P.first(g)
    arrows: list[tuple[str, P.Stage[Tagged, Tagged], P.Stage[Tagged, Tagged]]] = [
        (arrow.name, P.left(arrow), P.stage(functools.partial(on_left, fn))) for arrow, fn in ARROWS
    ]
    right_arr: P.Stage[Tagged, Tagged] = P.stage(functools.partial(on_right, inc))  # arr (id +++ g)
    return {
        **{
            f"left_arr_{name}": law_sides(tagged, left, right) for name, left, right in arrows
        },  # left (arr f) = arr (left f)
        "left_of_chain": law_sides(tagged, left_f_g, left_f | left_g),  # left (f >>> g) = left f >>> left g
        # f >>> arr Left = arr Left >>> left f
        "to_left_then_left": law_sides(items, f | P.stage(to_left), P.stage(to_left) | left_f),
        "left_commutes_with_right_arr": law_sides(tagged, left_f | right_arr, right_arr | left_f),
        # left (left f) >>> arr assocsum = arr assocsum >>> left f
        "left_left_then_assoc_sum": law_sides(
            nested, left_left_f | P.stage(assoc_sum), P.stage(assoc_sum) | left_f_nested
        ),
        "route_is_left_then_right": law_sides(tagged, P.route(f, g), left_f | right_g),  # f +++ g = left f >>> right g
        "lifted_route_distributes": law_sides(
            pairs, lifted_route, P.stage(dist_sum) | P.route(first_f, first_g) | P.stage(undist_sum)
        ),
    }


CHOICE_LAWS = list(choice_law_sides(P.identity(), P.identity(), []))


@pytest.mark.parametrize("law", CHOICE_LAWS)
@given(stages(), stages(), INPUTS)
def test_choice_laws(law: str, f: P.Stage[int, int], g: P.Stage[int, int], items: list[int]) -> None:
    check_meanings(choice_law_sides(f, g, items)[law])


@pytest.mark.parametrize("law", CHOICE_LAWS)
@given(stages(), stages(), NONEMPTY_INPUTS)
def test_runs_satisfy_choice_laws(law: str, f: P.Stage[int, int], g: P.Stage[int, int], items: list[int]) -> None:
    check_runs(choice_law_sides(f, g, items)[law])


def gather_and_loop_law_sides(f: P.Stage[int, int], items: list[int]) -> dict[str, LawSides]:
    """Both sides of laws of `gather` and `loop`, with lifted ones and ones in a `product` branch,
    applied to the same inputs, by law."""
    pairs = pairs_of(items)
    countdowns = [countdown for i in items for countdown in with_depth(i)]
    countdown_pairs = [(countdown, -i) for i in items for countdown in with_depth(i)]
    flattened: P.Stage[list[int], int] = P.flatten()
    lifted_gather: P.Stage[tuple[int, int], tuple[list[int], int]] = P.first(P.gather(f))
    gather_in_branch: P.Stage[tuple[int, int], tuple[list[int], int]] = P.product(P.gather(f), P.identity())
    mirrored_gather: P.Stage[tuple[int, int], tuple[int, list[int]]] = P.second(P.gather(f))
    body = countdown_body(f)
    looped: P.Stage[Countdown, int] = P.loop(body)
    h = P.stage(at_most_three)  # fixed: a generated stage after the loop would fan out f's outputs again
    mapped_exits: P.Stage[P.Left[Countdown] | P.Right[int], P.Left[Countdown] | P.Right[int]] = P.right(h)
    unfolded: P.Stage[Countdown, int] = body | P.left(looped) | P.untag()
    lifted_loop: P.Stage[tuple[Countdown, int], tuple[int, int]] = P.first(looped)
    loop_in_branch: P.Stage[tuple[Countdown, int], tuple[int, int]] = P.product(looped, P.identity())
    mirrored_loop: P.Stage[tuple[int, Countdown], tuple[int, int]] = P.second(looped)
    exits_at_once: P.Stage[int, int] = P.loop(f | P.stage(to_right))
    first_f: P.Stage[tuple[int, int], tuple[int, int]] = P.first(f)
    second_f: P.Stage[tuple[int, int], tuple[int, int]] = P.second(f)
    return {
        "flattening_undoes_gather": law_sides(items, P.gather(f) | flattened, f),
        # ...per input (kept x)
        "flattening_undoes_lifted_gather": law_sides(pairs, lifted_gather | P.first(flattened), first_f),
        "flattening_undoes_gather_in_branch": law_sides(pairs, gather_in_branch | P.first(flattened), first_f),
        "flattening_undoes_mirrored_gather": law_sides(pairs, mirrored_gather | P.second(flattened), second_f),
        "gather_of_one_to_one_stage": law_sides(items, P.gather(P.stage(inc)), P.stage(inc) | P.stage(singleton)),
        "loop_without_feedback": law_sides(items, exits_at_once, f),
        "loop_unfolds": law_sides(countdowns, looped, unfolded),  # loop f = f >>> left (loop f)
        "loop_is_natural_in_the_exit": law_sides(countdowns, looped | h, P.loop(body | mapped_exits)),
        "lifted_loop_then_fst": law_sides(
            countdown_pairs, lifted_loop | P.fst(), first_of_countdown | looped
        ),  # first f >>> arr fst = arr fst >>> f
        "lifted_loop_is_loop_in_branch": law_sides(countdown_pairs, lifted_loop, loop_in_branch),
        "mirrored_loop_is_swapped_lifted_loop": law_sides(
            countdown_pairs, lifted_loop, swap_countdown | mirrored_loop | P.swap()
        ),
    }


GATHER_AND_LOOP_LAWS = list(gather_and_loop_law_sides(P.identity(), []))


@pytest.mark.parametrize("law", GATHER_AND_LOOP_LAWS)
@given(stages(), INPUTS)
def test_gather_and_loop_laws(law: str, f: P.Stage[int, int], items: list[int]) -> None:
    check_meanings(gather_and_loop_law_sides(f, items)[law])


@pytest.mark.parametrize("law", GATHER_AND_LOOP_LAWS)
@given(stages(), NONEMPTY_INPUTS)
def test_runs_satisfy_gather_and_loop_laws(law: str, f: P.Stage[int, int], items: list[int]) -> None:
    check_runs(gather_and_loop_law_sides(f, items)[law])
