"""Fusion: the optimisation pass before streaming runs."""

import asyncio
from collections.abc import AsyncGenerator, Callable, Iterable, Iterator
from dataclasses import replace
from enum import Enum
from typing import Final, Never, cast

from strom._closing import close_if_closable
from strom._stages.focus import Focus
from strom._stages.model import (
    AsyncExpand,
    Chain,
    Expand,
    FocusedStep,
    Gather,
    Join,
    Leaf,
    Loop,
    Route,
    Stage,
    Step,
)


# ---- fusion: an optimisation pass of streaming runs (no new representation)
# `fused` rewrites a stage before a streaming run: each maximal sequence of two or more consecutive
# event-loop steps (plain or lifted) becomes one ordinary `Step` (a group) named by its chain, with
# an `AsyncExpand` leaf whose function composes theirs depth-first: no task and no queue between
# them. Steps that wait and joins stay boundaries; join branches are fused separately. The reference
# semantics runs the stage unfused; the interpreters do not know about fusion. Observable: a group is
# ONE step occurrence (metrics, step ids, its errors noted with its name). The pass is idempotent: a
# group is no event-loop step.
# `fused` walks a chain's elements in one loop, recursing only into join branches. The elements are
# held as `_Element` (any stage), so putting them back together takes casts (the library's others: one in
# the iterator registry, `strom._runtime.iterator_registry`):
# adjacent elements fit because they come from one chain (checked by the tests that fusion keeps
# the meaning, not by the type checkers).
class _Skip(Enum):
    """`SKIP`: in the outputs of a composed function, a member's input without outputs.

    Stream fusion's `Skip` step (Coutts et al. 2007). Lets `_fair` count dropped items; never an
    output."""

    SKIP = 0


_SKIP_BUDGET: Final = 100
"""Dropped items (SKIPs) after which a group lets other tasks run."""


def _focus_sync[I, O, A, B, K](
    focus: Focus[I, O, A, B, K], fn: Callable[[A], Iterable[B]]
) -> Callable[[I], Iterator[O]]:
    """A lifted member of a group: `focus` applied around `fn` synchronously.

    The task loop applies a step's focus; inside a group there is no task loop between members."""
    split, merge, finish = focus.split, focus.merge, focus.finish

    def apply(item: I) -> Iterator[O]:
        a, kept = split(item)
        try:
            iterator = iter(fn(a))
            try:
                for b in iterator:
                    yield merge(b, kept)
            finally:
                close_if_closable(iterator)
        finally:
            if finish is not None:
                finish(kept)

    return apply


def _then[A, B, C](
    f: Callable[[A], Iterable[B]], g: Callable[[B], Iterable[C | _Skip]]
) -> Callable[[A], Iterator[C | _Skip]]:
    """f (one member's function: no SKIPs), then g on each of its outputs, depth-first.

    Kleisli composition of the list monad; a SKIP for each output of f on which g has no outputs."""

    def both(item: A) -> Iterator[C | _Skip]:
        iterator = iter(f(item))
        try:
            for b in iterator:
                outs = iter(g(b))
                try:
                    produced = False
                    for c in outs:
                        produced = True
                        yield c
                finally:
                    close_if_closable(outs)
                if not produced:
                    yield _Skip.SKIP
        finally:
            close_if_closable(iterator)

    return both


def _fair[I, O](group_fn: Callable[[I], Iterable[O | _Skip]]) -> Callable[[I], AsyncGenerator[O]]:
    """The outputs of `group_fn` without its SKIPs; other tasks run after every `_SKIP_BUDGET` SKIPs.

    A group whose members drop items never puts to its queue, so nothing else would make it wait
    (e.g. a filter after a large source)."""

    async def outputs(item: I) -> AsyncGenerator[O]:
        iterator = iter(group_fn(item))
        num_skipped = 0
        try:
            for out in iterator:
                if out is not _Skip.SKIP:
                    yield out
                    continue
                num_skipped += 1
                if num_skipped == _SKIP_BUDGET:
                    num_skipped = 0
                    await asyncio.sleep(0)  # fairness: other tasks run
        finally:  # created here, so closed here (also when the consumer stops early)
            close_if_closable(iterator)

    return outputs


type _Element = Stage[Never, object]
"""Any stage (`Stage` is contravariant in its input, covariant in its output): one element of a chain
while `fused` walks it. Adjacent elements fit together because they come from one chain."""


type _Member = tuple[_Element, Callable[[Never], Iterable[object]]]
"""An event-loop step of a chain (plain or lifted) and its function (see `_member_fn`)."""


def fused[I, O](stage: Stage[I, O]) -> Stage[I, O]:
    """`stage` with each maximal sequence of two or more consecutive event-loop steps fused.

    Each such sequence becomes one step (a group), also inside join and route branches and the bodies of
    gathers and loops. One pass over the
    chain's elements: those `ahead` (a stack, chains unfold as they come up), the current group's
    `members`, and those `done`."""
    ahead: list[_Element] = [stage]
    members: list[_Member] = []
    done: list[_Element] = []
    while ahead:
        element = ahead.pop()
        match element:
            case Chain():
                ahead += (element.tail, element.head)
                continue
            case Join():
                element = _fused_join(element)  # recursion only into branches
            case Route():
                element = _fused_route(element)
            case Gather():
                element = _fused_gather(element)
            case Loop():
                element = _fused_loop(element)
            case _:  # a step: as it is
                pass
        member_fn = _member_fn(element)
        if member_fn is not None:
            members.append((element, member_fn))
            continue
        done += _grouped(members)
        members = []
        done.append(element)
    done += _grouped(members)
    return cast(Stage[I, O], _chained(done))


def _grouped(members: list[_Member]) -> list[_Element]:
    """A group's members as the steps that run them.

    None, the single one as it is, or ONE step named by their chain, with an `AsyncExpand` leaf
    (concurrency 1, queue size inferred)."""
    if len(members) < 2:
        return [element for element, _ in members]
    group_fn = members[-1][1]
    for _, member_fn in reversed(members[:-1]):  # right-nested: `_then`'s first function is one member
        group_fn = _then(member_fn, cast(Callable[[object], Iterable[object | _Skip]], group_fn))
    name = " | ".join(element.name for element, _ in members)
    return [Step[Never, object](name=name, leaf=AsyncExpand(fn=_fair(group_fn)))]


def _chained(elements: list[_Element]) -> _Element:
    """The chain of `elements`, in order."""
    stage = elements[-1]
    for element in reversed(elements[:-1]):
        stage = element | cast(Stage[object, object], stage)
    return stage


def _member_fn(element: _Element) -> Callable[[Never], Iterable[object]] | None:
    """The function of an event-loop step as a group member (a lifted one's with its focus).

    None for any other element (a step that waits, or a join)."""
    match element:
        case Step():
            return _event_loop_fn(element.leaf)
        case FocusedStep():
            return _member_fn_focused(element)
        case _:
            return None


def _member_fn_focused[I, O, A, B, K](
    focused: FocusedStep[I, O, A, B, K],
) -> Callable[[I], Iterable[O]] | None:
    fn = _event_loop_fn(focused.step.leaf)
    return None if fn is None else _focus_sync(focused.focus, fn)


def _event_loop_fn[I, O](leaf: Leaf[I, O]) -> Callable[[I], Iterable[O]] | None:
    """The user's function of an event-loop leaf; None for a leaf that waits."""
    match leaf:
        case Expand(resource=None):
            return leaf.fn
        case Expand() | AsyncExpand():
            return None


def _fused_join[I, O, A, B, C, D, T](join: Join[I, O, A, B, C, D, T]) -> Stage[I, O]:
    return replace(join, left=fused(join.left), right=fused(join.right))


def _fused_route[I, O, A, B, C, D](route: Route[I, O, A, B, C, D]) -> Stage[I, O]:
    return replace(route, left=fused(route.left), right=fused(route.right))


def _fused_gather[I, O, A, B, K](gather: Gather[I, O, A, B, K]) -> Stage[I, O]:
    return replace(gather, body=fused(gather.body))


def _fused_loop[I, O, A, B, K](loop: Loop[I, O, A, B, K]) -> Stage[I, O]:
    return replace(loop, body=fused(loop.body))
