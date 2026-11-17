"""Generated pipelines (Hypothesis) on ints: 1:1 stages (`maps`) and 1:0..n stages (`stages`, at most
`MAX_OUTPUTS` per input), nested arbitrarily, with generated concurrency and buffer sizes. Shrinking reduces a
failure to a minimal pipeline. And the hash pipelines (`hash_stages`), whose leaves are drawn part by part and
record their calls."""

import asyncio
import itertools
import threading
import time
from collections import Counter
from collections.abc import AsyncIterator, Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, NamedTuple

from helpers import (
    Countdown,
    Failure,
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
generated stage carries its bound (`Bounded`); why: `docs/decisions/generated-stages.md`."""


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
    # not `filter`: its retries raise a HypothesisWarning (docs/decisions/generated-stages.md)
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


# ------------------------------------------------------------------ hash pipelines
# Generated pipelines whose leaves are drawn part by part: an item is an int, a leaf gives hashes of its input, and
# its fan-out, the kind of its step, its concurrency and its buffer are drawn independently. Every leaf records
# its calls in the `Calls` that is on (`recorded`).

_MASK = 2**64 - 1


def mix(item: int, salt: int) -> int:
    """A 64-bit hash of `item` and `salt` (SplitMix64)."""
    mixed = (item + (salt + 1) * 0x9E3779B97F4A7C15) & _MASK
    mixed = ((mixed ^ (mixed >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    mixed = ((mixed ^ (mixed >> 27)) * 0x94D049BB133111EB) & _MASK
    return mixed ^ (mixed >> 31)


class Calls:
    """What the hash leaves did in one run: `counts` by leaf and input, and `num_above_limit`, the calls that
    started while their leaf had `concurrency` calls running already. The call of a lazy or async leaf runs until
    its iterator ends or is closed.

    `overlapping`: a call in a pool sleeps 50 µs for one input in four, so that the calls of a leaf overlap
    on pool threads; never on the inline backend, where the sleep would hold the event loop."""

    def __init__(self, overlapping: bool = False) -> None:
        self.overlapping = overlapping
        self.counts: Counter[tuple[int, int]] = Counter()
        self.num_above_limit = 0
        self._num_running: Counter[int] = Counter()
        self._lock = threading.Lock()

    @contextmanager
    def call(self, leaf: HashLeaf, item: int) -> Generator[None]:
        with self._lock:
            self.counts[leaf.number, item] += 1
            self._num_running[leaf.number] += 1
            self.num_above_limit += self._num_running[leaf.number] > leaf.concurrency
        try:
            yield
        finally:
            with self._lock:
                self._num_running[leaf.number] -= 1

    def overlap(self, leaf: HashLeaf, item: int) -> None:
        if self.overlapping and not mix(item, leaf.salt ^ 0x5A5A) & 3:
            time.sleep(0.00005)


_calls = Calls()  # of the run that is on: a module variable, because pool threads see no context variable of the loop


@contextmanager
def recorded(overlapping: bool = False) -> Generator[Calls]:
    """The `Calls` that the hash leaves record into during the block."""
    global _calls
    before, _calls = _calls, Calls(overlapping)
    try:
        yield _calls
    finally:
        _calls = before


type FanOut = Literal["one", "some", "keep", "fail"]


@dataclass(frozen=True)
class HashLeaf:
    """The function of a hash leaf, as its methods (an instance pickles, for a backend without shared memory):
    `on_loop` and `in_pool` return a list, `lazily` an iterator and `asynchronously` an async iterator of the same
    items. `number` tells the leaves of a pipeline apart; `concurrency` is that of its step."""

    number: int
    salt: int
    fan_out: FanOut
    concurrency: int

    def outputs(self, item: int) -> list[int]:
        hashed = mix(item, self.salt)
        match self.fan_out:
            case "one":
                return [hashed]
            case "some":
                return [mix(hashed, index) for index in range(hashed % 4)]
            case "keep":
                return [hashed] if hashed & 1 else []
            case "fail":
                if hashed % 16 == 0:
                    raise Failure(item)
                return [hashed]

    def on_loop(self, item: int) -> list[int]:
        with _calls.call(self, item):
            return self.outputs(item)

    def in_pool(self, item: int) -> list[int]:
        calls = _calls
        with calls.call(self, item):
            calls.overlap(self, item)
            return self.outputs(item)

    def as_one_item(self, item: int) -> list[list[int]]:
        return [self.in_pool(item)]  # ONE item: a list

    def keeps(self, item: int) -> bool:
        with _calls.call(self, item):
            return bool(mix(item, self.salt) & 1)

    def lazily(self, item: int) -> Iterator[int]:
        calls = _calls
        with calls.call(self, item):
            for out in self.outputs(item):
                calls.overlap(self, out)
                yield out

    async def asynchronously(self, item: int) -> AsyncIterator[int]:
        with _calls.call(self, item):
            for out in self.outputs(item):
                await asyncio.sleep(0)
                yield out


type LeafKind = Literal["loop", "io list", "io one list", "io iterator", "cpu", "async"]
_leaf_numbers = itertools.count()


def hash_leaf(salt: int, fan_out: FanOut, kind: LeafKind, concurrency: int, buffer_size: int) -> Bounded:
    leaf = HashLeaf(next(_leaf_numbers), salt, fan_out, 1 if kind == "loop" else concurrency)
    name = f"{fan_out}_{salt}"
    stage: P.Stage[int, int]
    match kind:
        case "loop":
            stage = P.stage(leaf.on_loop, name=name)
        case "io list":
            stage = P.io_stage(leaf.in_pool, concurrency=concurrency, buffer_size=buffer_size, name=name)
        case "io one list":
            listed = P.io_stage(leaf.as_one_item, concurrency=concurrency, buffer_size=buffer_size, name=name)
            stage = listed | P.flatten()
        case "io iterator":
            stage = P.io_stage(leaf.lazily, concurrency=concurrency, buffer_size=buffer_size, name=name)
        case "cpu":
            stage = P.cpu_stage(leaf.in_pool, concurrency=concurrency, name=name)
        case "async":
            stage = P.async_stage(leaf.asynchronously, concurrency=concurrency, buffer_size=buffer_size, name=name)
    return Bounded(stage, 3 if fan_out == "some" else 1)


FAN_OUTS: list[FanOut] = ["one", "one", "one", "some", "some", "keep", "keep", "fail"]  # a failing leaf in eight
LEAF_KINDS: list[LeafKind] = ["loop", "io list", "io one list", "io iterator", "cpu", "async"]


def hash_where(salt: int) -> Bounded:
    """Keeps the items whose hash is odd, as they are."""
    return Bounded(P.where(HashLeaf(next(_leaf_numbers), salt, "keep", 1).keeps, name=f"where_{salt}"), 1)


def _hash_stages(fan_outs: list[FanOut], ordered: bool, one_to_one: bool) -> st.SearchStrategy[P.Stage[int, int]]:
    salts = st.integers(0, 2**20)
    leaf = st.builds(
        hash_leaf,
        salts,
        st.sampled_from(fan_outs),
        st.sampled_from(LEAF_KINDS),
        st.just(1) if ordered else st.sampled_from([1, 2, 4]),
        BUFFER,
    )
    plumbing = [st.builds(lambda: Bounded(P.identity(), 1))]
    if not one_to_one:
        plumbing.append(st.builds(hash_where, salts))

    def combined(inner: st.SearchStrategy[Bounded]) -> st.SearchStrategy[Bounded]:
        options = [st.builds(chain_of, inner, inner), st.builds(first_of, inner), st.builds(second_of, inner)]
        if not ordered:  # product, route, gather and loop emit as their parts deliver
            options.append(st.builds(product_of, inner, inner, BUFFER))
            options.append(st.builds(route_of, inner, inner, BUFFER))
            if not one_to_one:  # a gather sums a list, a loop applies its body twice
                options.append(st.builds(gather_of, inner, IN_FLIGHT, BUFFER))
                options.append(st.builds(loop_of, inner, IN_FLIGHT, BUFFER))
        return within_bound(st.one_of(*options))

    # eight leaves of ten are hash leaves
    leaves = st.one_of(*[leaf] * 8, *plumbing)
    return st.recursive(leaves, combined, max_leaves=6).map(lambda bounded: bounded.stage)


def hash_stages(ordered: bool = False, failing: bool = True) -> st.SearchStrategy[P.Stage[int, int]]:
    """The combinations of `stages` over hash leaves, `P.where` and `P.identity`. With `failing`, about one
    example in 20 on `HASH_INPUTS` fails. `ordered`: every step has a concurrency of 1 and no part emits as its
    parts deliver, so a run gives the reference order."""
    return _hash_stages(FAN_OUTS if failing else [fan_out for fan_out in FAN_OUTS if fan_out != "fail"], ordered, False)


def hash_maps(ordered: bool = False) -> st.SearchStrategy[P.Stage[int, int]]:
    """1:1 hash pipelines, as `maps`: one output per input, and none fails."""
    return _hash_stages(["one"], ordered, True)


HASH_INPUTS = st.lists(st.integers(0, 2**32 - 1), min_size=1, max_size=20, unique=True)

INPUTS = st.lists(st.integers(-20, 20), max_size=40)
# for runs: about a third of the generated INPUTS were empty, and a run without inputs agrees trivially
# (`test_runs_without_inputs` in `interpreters/test_streaming.py` covers that case)
NONEMPTY_INPUTS = st.lists(st.integers(-20, 20), min_size=1, max_size=40)
