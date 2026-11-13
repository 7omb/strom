"""Generated pipelines (Hypothesis) on ints: 1:1 stages (`maps`) and 1:0..n stages (`stages`, at most
`MAX_OUTPUTS` per input), nested arbitrarily, with generated concurrency and buffer sizes. Shrinking reduces a
failure to a minimal pipeline."""

from typing import NamedTuple

from helpers import (
    Countdown,
    add_pair,
    async_at_most_three,
    async_inc,
    at_most_three,
    at_most_three_lazily,
    countdown_body,
    double,
    inc,
    is_odd,
    neg,
    slow_double,
    with_depth,
)
from hypothesis import assume
from hypothesis import strategies as st

import strom as P


def at_most_three_as_list(item: int) -> list[list[int]]:
    return [at_most_three(item)]  # ONE item: a list


def sum_list(items: list[int]) -> list[int]:
    """The sum of a gathered list: the same whatever the order of the list."""
    return [sum(items)]


def looping(stage: P.Stage[int, int], concurrency: int = 10, buffer_size: int = 10) -> P.Stage[Countdown, int]:
    """A loop with the `countdown_body` of `stage`."""
    return P.loop(countdown_body(stage), concurrency=concurrency, buffer_size=buffer_size)


BUFFER = st.sampled_from([1, 2, 10])


def maps(ordered: bool = False) -> st.SearchStrategy[P.Stage[int, int]]:
    conc = st.just(1) if ordered else st.sampled_from([1, 2, 4])
    leaf = st.one_of(
        st.builds(lambda: P.stage(inc)),
        st.builds(
            lambda concurrency, buffer_size: P.io_stage(double, concurrency=concurrency, buffer_size=buffer_size),
            conc,
            BUFFER,
        ),
        st.builds(
            lambda concurrency, buffer_size: P.io_stage(slow_double, concurrency=concurrency, buffer_size=buffer_size),
            conc,
            BUFFER,
        ),
        st.builds(lambda concurrency: P.cpu_stage(neg, concurrency=concurrency), conc),
        st.builds(lambda concurrency: P.async_stage(async_inc, concurrency=concurrency), conc),
        st.builds(P.identity),
    )

    def combined(inner: st.SearchStrategy[P.Stage[int, int]]) -> st.SearchStrategy[P.Stage[int, int]]:
        options = [
            st.builds(lambda head, tail: head | tail, inner, inner),
            st.builds(
                lambda left, right, buffer_size: (
                    P.duplicate() | P.product(left, right, buffer_size=buffer_size) | P.stage(add_pair)
                ),
                inner,
                inner,
                BUFFER,
            ),
            st.builds(lambda stage: P.duplicate() | P.first(stage) | P.stage(add_pair), inner),
            st.builds(lambda stage: P.duplicate() | P.second(stage) | P.stage(add_pair), inner),
        ]
        if not ordered:  # route emits the outputs of its branches as they arrive
            options.append(st.builds(routed, inner, inner, BUFFER))
        return st.one_of(*options)

    return st.recursive(leaf, combined, max_leaves=6)


def routed(left: P.Stage[int, int], right: P.Stage[int, int], buffer_size: int) -> P.Stage[int, int]:
    """A route of two stages on items tagged by parity."""
    return P.tag_by(is_odd) | P.route(left, right, buffer_size=buffer_size) | P.untag()


IN_FLIGHT = st.sampled_from([1, 2, 10])


def gathered(stage: P.Stage[int, int], concurrency: int, buffer_size: int) -> P.Stage[int, int]:
    """A gather of `stage`, each list summed."""
    return P.gather(stage, concurrency=concurrency, buffer_size=buffer_size) | P.stage(sum_list)


def iterated(stage: P.Stage[int, int], concurrency: int, buffer_size: int) -> P.Stage[int, int]:
    """A loop whose body applies `stage` and feeds the item back at most once."""
    return P.stage(with_depth) | looping(stage, concurrency=concurrency, buffer_size=buffer_size)


MAX_OUTPUTS = 9
"""The most outputs per input of a generated stage (`stages`): two 1:3 leaves in a row or in a `product`. Each
generated stage carries its bound (`Bounded`); why: `docs/decisions/test-settings.md`."""


class Bounded(NamedTuple):
    """A generated stage and the most outputs it gives per input."""

    stage: P.Stage[int, int]
    max_outputs: int


# The combinations of generated stages (`stages`), each with the bound of its outputs per input.
def chain_of(head: Bounded, tail: Bounded) -> Bounded:
    return Bounded(head.stage | tail.stage, head.max_outputs * tail.max_outputs)


def paired() -> P.Stage[int, tuple[int, int]]:
    return P.duplicate()  # typed by the return: mypy infers no input type for it at the head of a chain


def first_of(bounded: Bounded) -> Bounded:
    return Bounded(paired() | P.first(bounded.stage) | P.stage(add_pair), bounded.max_outputs)


def second_of(bounded: Bounded) -> Bounded:
    return Bounded(paired() | P.second(bounded.stage) | P.stage(add_pair), bounded.max_outputs)


def product_of(left: Bounded, right: Bounded, buffer_size: int) -> Bounded:
    """Every output of `left` paired with every one of `right`."""
    product = P.product(left.stage, right.stage, buffer_size=buffer_size)
    return Bounded(paired() | product | P.stage(add_pair), left.max_outputs * right.max_outputs)


def route_of(left: Bounded, right: Bounded, buffer_size: int) -> Bounded:
    return Bounded(routed(left.stage, right.stage, buffer_size), max(left.max_outputs, right.max_outputs))


def gather_of(bounded: Bounded, concurrency: int, buffer_size: int) -> Bounded:
    return Bounded(gathered(bounded.stage, concurrency, buffer_size), 1)


def loop_of(bounded: Bounded, concurrency: int, buffer_size: int) -> Bounded:
    """The body applies the stage again to each output it feeds back."""
    return Bounded(iterated(bounded.stage, concurrency, buffer_size), bounded.max_outputs**2)


@st.composite
def within_bound(draw: st.DrawFn, generated: st.SearchStrategy[Bounded]) -> Bounded:
    bounded = draw(generated)
    # not `filter`: its retries raise a HypothesisWarning (docs/decisions/test-settings.md)
    assume(bounded.max_outputs <= MAX_OUTPUTS)
    return bounded


def stages(ordered: bool = False) -> st.SearchStrategy[P.Stage[int, int]]:
    conc = st.just(1) if ordered else st.sampled_from([1, 2, 4])
    one_to_three = st.one_of(
        st.builds(lambda: P.stage(at_most_three)),
        st.builds(
            lambda concurrency, buffer_size: (
                P.io_stage(at_most_three_as_list, concurrency=concurrency, buffer_size=buffer_size) | P.flatten()
            ),
            conc,
            BUFFER,
        ),
        st.builds(
            lambda concurrency, buffer_size: P.async_stage(
                async_at_most_three, concurrency=concurrency, buffer_size=buffer_size
            ),
            conc,
            BUFFER,
        ),
        st.builds(
            lambda concurrency, buffer_size: P.io_stage(
                at_most_three_lazily, concurrency=concurrency, buffer_size=buffer_size
            ),
            conc,
            BUFFER,
        ),
        st.builds(lambda concurrency: P.cpu_stage(at_most_three_lazily, concurrency=concurrency), conc),
    )
    leaf = st.one_of(
        st.builds(Bounded, maps(ordered), st.just(1)),
        st.builds(lambda: Bounded(P.where(is_odd), 1)),
        st.builds(Bounded, one_to_three, st.just(3)),
    )

    def combined(inner: st.SearchStrategy[Bounded]) -> st.SearchStrategy[Bounded]:
        options = [
            st.builds(chain_of, inner, inner),
            st.builds(first_of, inner),
            st.builds(second_of, inner),
        ]
        if not ordered:  # product, route, gather and loop emit as their parts deliver
            options.append(st.builds(product_of, inner, inner, BUFFER))
            options.append(st.builds(route_of, inner, inner, BUFFER))
            options.append(st.builds(gather_of, inner, IN_FLIGHT, BUFFER))
            options.append(st.builds(loop_of, inner, IN_FLIGHT, BUFFER))
        return within_bound(st.one_of(*options))

    return st.recursive(leaf, combined, max_leaves=6).map(lambda bounded: bounded.stage)


INPUTS = st.lists(st.integers(-20, 20), max_size=40)
# for runs: about a third of the generated INPUTS were empty, and a run without inputs agrees trivially
# (`test_runs_without_inputs` in `interpreters/test_streaming.py` covers that case)
NONEMPTY_INPUTS = st.lists(st.integers(-20, 20), min_size=1, max_size=40)
