"""Lifting: stage rewrites that apply a stage to one element of a pair, or count its items.

Each lifting is pushed down onto the steps: a plain step gets the lifting's focus, a stage that holds a focus
(`Focused`: a focused step, a join, a gather, a loop) gets its focus wrapped and keeps everything else
(`Focused.with_focus`), a chain and a route lift their parts."""

from collections.abc import Callable
from typing import assert_never

from strom._stages.focus import (
    Count,
    Focus,
    Sequenced,
    counted,
    counting_focus,
    first_focus,
    first_of,
    second_focus,
    second_of,
)
from strom._stages.model import Chain, Focused, FocusedStep, Left, Right, Route, Stage, Step


def lift_first[I, O, X](stage: Stage[I, O]) -> Stage[tuple[I, X], tuple[O, X]]:
    """`stage` applied to the first element of pairs, pushed down onto every step.

    So each step keeps its name and settings: first(f | g) = first(f) | first(g)."""
    match stage:
        case Step():
            return _lift_first_step(stage)
        case Focused():
            return _lift_first_focused(stage)
        case Chain():
            return _lift_first_chain(stage)
        case Route():
            return _lift_first_route(stage)
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def _lift_first_step[I, O, X](step: Step[I, O]) -> Stage[tuple[I, X], tuple[O, X]]:
    focus: Focus[tuple[I, X], tuple[O, X], I, O, X] = first_focus()
    return FocusedStep(name=step.name, step=step, focus=focus)


def _lift_first_focused[I, O, A, B, K, X](focused: Focused[I, O, A, B, K]) -> Stage[tuple[I, X], tuple[O, X]]:
    """first of a focused step, a join, a gather or a loop: x travels with the stage's own kept value, so a
    join needs no further join or queue, and the body of a gather or loop (and a loop's feedback) is not
    lifted."""
    return focused.with_focus(first_of(focused.focus))


def _lift_first_chain[I, M, O, X](chain: Chain[I, M, O]) -> Stage[tuple[I, X], tuple[O, X]]:
    head: Stage[tuple[I, X], tuple[M, X]] = lift_first(chain.head)
    tail: Stage[tuple[M, X], tuple[O, X]] = lift_first(chain.tail)
    return head | tail


def _lift_first_route[I, O, A, B, C, D, X](route: Route[I, O, A, B, C, D]) -> Stage[tuple[I, X], tuple[O, X]]:
    """first(R): x goes with the input into the chosen branch, which is lifted to carry it."""
    choose: Callable[[tuple[I, X]], Left[tuple[A, X]] | Right[tuple[C, X]]] = _choose_first(route.choose)
    lifted_left: Stage[tuple[A, X], tuple[B, X]] = lift_first(route.left)
    lifted_right: Stage[tuple[C, X], tuple[D, X]] = lift_first(route.right)
    from_left: Callable[[tuple[B, X]], tuple[O, X]] = _from_first(route.from_left)
    from_right: Callable[[tuple[D, X]], tuple[O, X]] = _from_first(route.from_right)
    return Route(
        name=route.name,
        choose=choose,
        left=lifted_left,
        right=lifted_right,
        from_left=from_left,
        from_right=from_right,
        buffer_size=route.buffer_size,
    )


# Lifting a route composes its functions with these (dist and undist of a product over a sum). Like
# the focus wrappers, they take the inner function, but the passed-through type X is bound by no
# argument: the lifting functions annotate their results, so that all three checkers check them.
def _choose_first[I, A, C, X](
    choose: Callable[[I], Left[A] | Right[C]],
) -> Callable[[tuple[I, X]], Left[tuple[A, X]] | Right[tuple[C, X]]]:
    """`choose` on the first element; the chosen branch's input is paired with the second one."""

    def choose_pair(pair: tuple[I, X]) -> Left[tuple[A, X]] | Right[tuple[C, X]]:
        item, x = pair  # unpacked: an input that is not a pair raises
        match choose(item):
            case Left(a):
                return Left((a, x))
            case Right(c):
                return Right((c, x))
            case unknown:
                assert_never(unknown)

    return choose_pair


def _choose_second[I, A, C, X](
    choose: Callable[[I], Left[A] | Right[C]],
) -> Callable[[tuple[X, I]], Left[tuple[X, A]] | Right[tuple[X, C]]]:
    """Mirror image of `_choose_first`: `choose` on the second element."""

    def choose_pair(pair: tuple[X, I]) -> Left[tuple[X, A]] | Right[tuple[X, C]]:
        x, item = pair
        match choose(item):
            case Left(a):
                return Left((x, a))
            case Right(c):
                return Right((x, c))
            case unknown:
                assert_never(unknown)

    return choose_pair


def _from_first[B, O, X](from_branch: Callable[[B], O]) -> Callable[[tuple[B, X]], tuple[O, X]]:
    """`from_branch` on the first element; the second one stays."""

    def from_pair(pair: tuple[B, X]) -> tuple[O, X]:
        return from_branch(pair[0]), pair[1]

    return from_pair


def _from_second[B, O, X](from_branch: Callable[[B], O]) -> Callable[[tuple[X, B]], tuple[X, O]]:
    """Mirror image of `_from_first`: `from_branch` on the second element."""

    def from_pair(pair: tuple[X, B]) -> tuple[X, O]:
        return pair[0], from_branch(pair[1])

    return from_pair


def lift_second[I, O, X](stage: Stage[I, O]) -> Stage[tuple[X, I], tuple[X, O]]:
    """Mirror image of `lift_first`: second(f | g) = second(f) | second(g)."""
    match stage:
        case Step():
            return _lift_second_step(stage)
        case Focused():
            return _lift_second_focused(stage)
        case Chain():
            return _lift_second_chain(stage)
        case Route():
            return _lift_second_route(stage)
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def _lift_second_step[I, O, X](step: Step[I, O]) -> Stage[tuple[X, I], tuple[X, O]]:
    focus: Focus[tuple[X, I], tuple[X, O], I, O, X] = second_focus()
    return FocusedStep(name=step.name, step=step, focus=focus)


def _lift_second_focused[I, O, A, B, K, X](focused: Focused[I, O, A, B, K]) -> Stage[tuple[X, I], tuple[X, O]]:
    """Mirror image of `_lift_first_focused`."""
    return focused.with_focus(second_of(focused.focus))


def _lift_second_chain[I, M, O, X](chain: Chain[I, M, O]) -> Stage[tuple[X, I], tuple[X, O]]:
    head: Stage[tuple[X, I], tuple[X, M]] = lift_second(chain.head)
    tail: Stage[tuple[X, M], tuple[X, O]] = lift_second(chain.tail)
    return head | tail


def _lift_second_route[I, O, A, B, C, D, X](route: Route[I, O, A, B, C, D]) -> Stage[tuple[X, I], tuple[X, O]]:
    """Mirror image of `_lift_first_route`."""
    choose: Callable[[tuple[X, I]], Left[tuple[X, A]] | Right[tuple[X, C]]] = _choose_second(route.choose)
    lifted_left: Stage[tuple[X, A], tuple[X, B]] = lift_second(route.left)
    lifted_right: Stage[tuple[X, C], tuple[X, D]] = lift_second(route.right)
    from_left: Callable[[tuple[X, B]], tuple[X, O]] = _from_second(route.from_left)
    from_right: Callable[[tuple[X, D]], tuple[X, O]] = _from_second(route.from_right)
    return Route(
        name=route.name,
        choose=choose,
        left=lifted_left,
        right=lifted_right,
        from_left=from_left,
        from_right=from_right,
        buffer_size=route.buffer_size,
    )


def lift_sequenced[I, O](stage: Stage[I, O], count: Count) -> Stage[Sequenced[I], Sequenced[O]]:
    """A `product` branch or the body of a `gather` or `loop`: `stage` on the first element of (item, sequence
    number) pairs.

    Pushed down like `lift_first`; every step counts the items of each input with `count`
    (`counting_focus` for a plain step, `counted` around the focus of a focused step). A nested join, gather
    or loop counts as one step (`counted` around its focus): +1 per output in its `merge`, -1 per input in
    its `finish`. A nested route is lifted like `_lift_first_route`: it passes each item on 1:1, so only
    its branches' steps count."""
    match stage:
        case Step():
            return _lift_sequenced_step(stage, count)
        case Focused():
            return _lift_sequenced_focused(stage, count)
        case Chain():
            return _lift_sequenced_chain(stage, count)
        case Route():
            return _lift_sequenced_route(stage, count)
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def _lift_sequenced_step[I, O](step: Step[I, O], count: Count) -> Stage[Sequenced[I], Sequenced[O]]:
    focus: Focus[Sequenced[I], Sequenced[O], I, O, int] = counting_focus(count)
    return FocusedStep(name=step.name, step=step, focus=focus)


def _lift_sequenced_focused[I, O, A, B, K](
    focused: Focused[I, O, A, B, K], count: Count
) -> Stage[Sequenced[I], Sequenced[O]]:
    return focused.with_focus(counted(focused.focus, count))


def _lift_sequenced_chain[I, M, O](chain: Chain[I, M, O], count: Count) -> Stage[Sequenced[I], Sequenced[O]]:
    head: Stage[Sequenced[I], Sequenced[M]] = lift_sequenced(chain.head, count)
    tail: Stage[Sequenced[M], Sequenced[O]] = lift_sequenced(chain.tail, count)
    return head | tail


def _lift_sequenced_route[I, O, A, B, C, D](
    route: Route[I, O, A, B, C, D], count: Count
) -> Stage[Sequenced[I], Sequenced[O]]:
    choose: Callable[[Sequenced[I]], Left[Sequenced[A]] | Right[Sequenced[C]]] = _choose_first(route.choose)
    lifted_left: Stage[Sequenced[A], Sequenced[B]] = lift_sequenced(route.left, count)
    lifted_right: Stage[Sequenced[C], Sequenced[D]] = lift_sequenced(route.right, count)
    from_left: Callable[[Sequenced[B]], Sequenced[O]] = _from_first(route.from_left)
    from_right: Callable[[Sequenced[D]], Sequenced[O]] = _from_first(route.from_right)
    return Route(
        name=route.name,
        choose=choose,
        left=lifted_left,
        right=lifted_right,
        from_left=from_left,
        from_right=from_right,
        buffer_size=route.buffer_size,
    )
