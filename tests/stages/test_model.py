"""Tests of `strom._stages.model`: the representation of stages (also of a function `Using` a handle)."""

import inspect
from collections.abc import AsyncIterator

from helpers import Countdown, bag, collect, countdown_body, many, meaning

import strom as P
from strom._stages.model import Stage


def inc(item: int) -> list[int]:
    return [item + 1]


async def async_inc(item: int) -> AsyncIterator[int]:
    yield item + 1


def is_odd(item: int) -> bool:
    return item % 2 == 1


def to_right(item: int) -> list[P.Left[int] | P.Right[int]]:
    return [P.Right(item)]


def test_repr_shows_the_name_and_the_settings_that_differ_from_the_defaults() -> None:
    pipeline = P.stage(inc) | P.io_stage(inc, concurrency=2, name="fetch") | P.io_stage(inc, name="print")
    assert repr(pipeline) == "<Stage 'inc | fetch | print' (fetch: io, concurrency=2; print: io)>"


def test_repr_of_a_stage_with_default_settings_is_its_name() -> None:
    assert repr(P.stage(inc) | P.where(bool)) == "<Stage 'inc | bool'>"


def test_repr_shows_steps_in_order_including_lifted_ones_and_the_settings_of_combinators() -> None:
    lifted: P.Stage[tuple[int, str], tuple[int, str]] = P.first(P.cpu_stage(inc, concurrency=4))
    passed: P.Stage[int, int] = P.identity()
    joined = P.product(P.async_stage(async_inc, buffer_size=3), passed, buffer_size=5)
    gathered = P.gather(P.stage(inc), concurrency=2, name="collected")
    assert repr(lifted) == "<Stage 'inc' (inc: cpu, concurrency=4)>"
    assert repr(joined) == (
        "<Stage 'product(async_inc, identity)' (async_inc: async, buffer_size=3; "
        "product(async_inc, identity): buffer_size=5)>"
    )
    assert repr(gathered) == "<Stage 'collected' (collected: concurrency=2)>"


def test_a_function_using_a_handle_names_its_stage_and_its_handle_in_the_repr() -> None:
    using = P.Using(inc, fn_name="inc", handle_name="engine")  # what `using` builds, without a handle
    assert repr(P.io_stage(using)) == "<Stage 'inc' (inc: io, using engine)>"
    assert repr(P.stage(using, name="on_loop")) == "<Stage 'on_loop' (on_loop: using engine)>"
    assert list(using(1)) == [2]


def test_repr_shows_no_internals() -> None:
    passed: P.Stage[int, int] = P.identity()
    for stage in [
        P.tag_by(is_odd) | P.route(P.io_stage(inc), passed),
        P.loop(P.stage(to_right)),
    ]:
        text = repr(stage)
        assert "Chain" not in text and "Route" not in text and "functools" not in text and "0x" not in text


# ---- every stage kind through every dispatcher (they end in `case _:`, so a missing arm is no type error)
def stage_kinds() -> set[type[object]]:
    """The stage kinds: every concrete subclass of `Stage` (the library's only; `Focused` is their abstract
    base, no kind)."""
    found: set[type[object]] = set()
    pending: list[type[object]] = [Stage]
    while pending:
        for kind in pending.pop().__subclasses__():
            if not inspect.isabstract(kind):
                found.add(kind)
            pending.append(kind)
    return found


def through_every_dispatcher[I, O](stage: P.Stage[I, O], inputs: list[I], checked: set[type[object]]) -> None:
    """`stage` gives the same items in the reference semantics (`run_reference`), a run (`fused`,
    `_run_streaming`, `_intake`), lifted onto either element of pairs (`lift_first`, `lift_second`) and in a
    `product` branch (`lift_sequenced`); its repr shows its io step (`display.settings`)."""
    expected = bag(meaning(stage, inputs))
    assert bag(collect(stage, inputs)) == expected
    firsts: P.Stage[tuple[I, str], tuple[O, str]] = P.first(stage)
    assert bag(collect(firsts, [(item, "x") for item in inputs])) == bag((out, "x") for out in meaning(stage, inputs))
    seconds: P.Stage[tuple[str, I], tuple[str, O]] = P.second(stage)
    assert bag(collect(seconds, [("x", item) for item in inputs])) == bag(("x", out) for out in meaning(stage, inputs))
    passed: P.Stage[str, str] = P.identity()
    branches = P.product(stage, passed)
    assert bag(collect(branches, [(item, "x") for item in inputs])) == bag((out, "x") for out in meaning(stage, inputs))
    assert "io" in repr(stage)
    checked.add(type(stage))


def test_every_stage_kind_goes_through_every_dispatcher() -> None:
    checked: set[type[object]] = set()
    io_inc = P.io_stage(inc)
    through_every_dispatcher(io_inc, [1, 2], checked)  # Step
    pairs: P.Stage[tuple[int, int], tuple[int, int]] = P.first(io_inc)
    through_every_dispatcher(pairs, [(1, 10)], checked)  # FocusedStep
    through_every_dispatcher(P.stage(inc) | io_inc, [1, 2], checked)  # Chain
    through_every_dispatcher(P.product(io_inc, P.stage(inc)), [(1, 10)], checked)  # Join
    routed: P.Stage[P.Left[int] | P.Right[int], P.Left[int] | P.Right[int]] = P.route(io_inc, P.stage(inc))
    tagged: list[P.Left[int] | P.Right[int]] = [P.Left(1), P.Right(10)]
    through_every_dispatcher(routed, tagged, checked)  # Route
    through_every_dispatcher(P.gather(P.io_stage(many)), [3, 0], checked)  # Gather
    looping: P.Stage[Countdown, int] = P.loop(countdown_body(io_inc))
    through_every_dispatcher(looping, [(1, 2), (5, 0)], checked)  # Loop
    assert checked == stage_kinds()  # a new kind needs a sample here, and an arm in every dispatcher
