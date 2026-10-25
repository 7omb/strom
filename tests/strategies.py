"""Generated pipelines (Hypothesis) on ints: 1:1 stages (`maps`) and 1:0..n stages (`stages`), nested
arbitrarily, with generated concurrency and buffer sizes. Shrinking reduces a failure to a minimal pipeline."""

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
            options.append(routed(inner))
        return st.one_of(*options)

    return st.recursive(leaf, combined, max_leaves=6)


def routed(inner: st.SearchStrategy[P.Stage[int, int]]) -> st.SearchStrategy[P.Stage[int, int]]:
    """A route of two generated stages on items tagged by parity."""
    return st.builds(
        lambda left, right, buffer_size: P.tag_by(is_odd) | P.route(left, right, buffer_size=buffer_size) | P.untag(),
        inner,
        inner,
        BUFFER,
    )


IN_FLIGHT = st.sampled_from([1, 2, 10])


def gathered(inner: st.SearchStrategy[P.Stage[int, int]]) -> st.SearchStrategy[P.Stage[int, int]]:
    """A gather of a generated stage, each list summed."""
    return st.builds(
        lambda stage, concurrency, buffer_size: (
            P.gather(stage, concurrency=concurrency, buffer_size=buffer_size) | P.stage(sum_list)
        ),
        inner,
        IN_FLIGHT,
        BUFFER,
    )


def iterated(inner: st.SearchStrategy[P.Stage[int, int]]) -> st.SearchStrategy[P.Stage[int, int]]:
    """A loop whose body applies a generated stage and feeds the item back at most once."""
    return st.builds(
        lambda stage, concurrency, buffer_size: (
            P.stage(with_depth) | looping(stage, concurrency=concurrency, buffer_size=buffer_size)
        ),
        inner,
        IN_FLIGHT,
        BUFFER,
    )


def stages(ordered: bool = False) -> st.SearchStrategy[P.Stage[int, int]]:
    conc = st.just(1) if ordered else st.sampled_from([1, 2, 4])
    leaf = st.one_of(
        maps(ordered),
        st.builds(lambda: P.stage(at_most_three)),
        st.builds(lambda: P.where(is_odd)),
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

    def combined(inner: st.SearchStrategy[P.Stage[int, int]]) -> st.SearchStrategy[P.Stage[int, int]]:
        options = [
            st.builds(lambda head, tail: head | tail, inner, inner),
            st.builds(lambda stage: P.duplicate() | P.first(stage) | P.stage(add_pair), inner),
            st.builds(lambda stage: P.duplicate() | P.second(stage) | P.stage(add_pair), inner),
        ]
        if not ordered:  # product, route, gather and loop emit as their parts deliver
            options.append(
                st.builds(
                    lambda left, right, buffer_size: (
                        P.duplicate() | P.product(left, right, buffer_size=buffer_size) | P.stage(add_pair)
                    ),
                    inner,
                    inner,
                    BUFFER,
                )
            )
            options.append(routed(inner))
            options.append(gathered(inner))
            options.append(iterated(inner))
        return st.one_of(*options)

    return st.recursive(leaf, combined, max_leaves=6)


INPUTS = st.lists(st.integers(-20, 20), max_size=40)
# for runs: about a third of the generated INPUTS were empty, and a run without inputs agrees trivially
# (`test_runs_without_inputs` in `interpreters/test_streaming.py` covers that case)
NONEMPTY_INPUTS = st.lists(st.integers(-20, 20), min_size=1, max_size=40)
