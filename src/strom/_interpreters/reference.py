"""The reference semantics: a stage as an ItemFn (`run_reference`; `strom.testing.evaluate` runs it).

It knows no pools, backends or offloaders: where a leaf's function runs and how its items are delivered is a
run's business, not part of what the leaf means."""

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import assert_never

from strom._closing import aclose_if_closable
from strom._interpreters.failures import stage_note
from strom._interpreters.item_fns import ItemFn, async_expanding, expanding
from strom._stages.focus import Focus
from strom._stages.model import (
    AsyncExpand,
    Chain,
    Expand,
    FocusedStep,
    Gather,
    Join,
    Leaf,
    Left,
    Loop,
    Right,
    Route,
    Stage,
    Step,
)


def run_reference[I, O](stage: Stage[I, O]) -> ItemFn[I, O]:
    """The ItemFn of a whole stage (the reference semantics as an ItemFn).

    Evaluated sequentially and depth-first (each output passes the rest of the chain before the next
    one is produced), without queues, concurrency, buffers or pools. A join evaluates its right
    branch completely, then its left one output by output. A specification for tests: a run of the
    stage must emit the same items (as a bag)."""
    match stage:
        case Step():
            return _run_reference_step(stage)
        case FocusedStep():
            return _run_reference_focused(stage)
        case Chain():
            return _run_reference_chain(stage)
        case Join():
            return _run_reference_join(stage)
        case Route():
            return _run_reference_route(stage)
        case Gather():
            return _run_reference_gather(stage)
        case Loop():
            return _run_reference_loop(stage)
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def _run_reference_step[I, O](step: Step[I, O]) -> ItemFn[I, O]:
    return _noted(step.name, _run_reference_leaf(step.leaf))


def _run_reference_focused[I, O, A, B, K](focused: FocusedStep[I, O, A, B, K]) -> ItemFn[I, O]:
    return _noted(focused.step.name, _focusing(focused.focus, _run_reference_leaf(focused.step.leaf)))


def _run_reference_leaf[I, O](leaf: Leaf[I, O]) -> ItemFn[I, O]:
    """What a leaf means: the items of its function on the input, lazily, in this thread, whatever resource a
    run would compute them on (blocking functions block: no pools, no concurrency)."""
    match leaf:
        case Expand():
            return expanding(leaf.fn)
        case AsyncExpand():
            return async_expanding(leaf.fn)


def _noted[I, O](name: str, item_fn: ItemFn[I, O]) -> ItemFn[I, O]:
    """`item_fn`, its errors noted with the stage's name, as a run notes them: a step names its own
    errors, a join, route, gather or loop every error that passes it (a chain none)."""

    async def noted(item: I) -> AsyncGenerator[O]:
        try:
            async with aclosing(item_fn(item)) as outs:
                async for out in outs:
                    yield out
        except Exception as error:
            error.add_note(stage_note(name))
            raise

    return noted


def _focusing[I, O, A, B, K](focus: Focus[I, O, A, B, K], inner_item_fn: ItemFn[A, B]) -> ItemFn[I, O]:
    """`focus` as an ItemFn around the leaf's (or a part's).

    Runs apply the focus in the task loop, without this generator."""
    split, merge, finish = focus.split, focus.merge, focus.finish

    async def item_fn(item: I) -> AsyncGenerator[O]:
        a, kept = split(item)
        outs = inner_item_fn(a)
        try:
            async for b in outs:
                yield merge(b, kept)
        except BaseException:  # stopped early: close at once
            await aclose_if_closable(outs)
            raise
        finally:
            if finish is not None:
                finish(kept)

    return item_fn


def _run_reference_chain[I, M, O](chain: Chain[I, M, O]) -> ItemFn[I, O]:
    run_head, run_tail = run_reference(chain.head), run_reference(chain.tail)

    async def evaluate(item: I) -> AsyncGenerator[O]:
        async with aclosing(run_head(item)) as mids:
            async for mid in mids:
                async with aclosing(run_tail(mid)) as outs:
                    async for out in outs:
                        yield out

    return evaluate


def _run_reference_join[I, O, A, B, C, D, T](join: Join[I, O, A, B, C, D, T]) -> ItemFn[I, O]:
    """The join's focus around the pairs (b, d) of each output b of left on a and d of right on c."""
    run_left, run_right = run_reference(join.left), run_reference(join.right)

    async def evaluate(branch_inputs: tuple[A, C]) -> AsyncGenerator[tuple[B, D]]:
        a, c = branch_inputs
        async with aclosing(run_right(c)) as right_outs:
            rights = [d async for d in right_outs]
        async with aclosing(run_left(a)) as left_outs:
            async for b in left_outs:
                for d in rights:
                    yield b, d

    return _noted(join.name, _focusing(join.focus, evaluate))


def _run_reference_route[I, O, A, B, C, D](route: Route[I, O, A, B, C, D]) -> ItemFn[I, O]:
    """The chosen branch on the input, each output passed through the branch's `from_*`."""
    run_left, run_right = run_reference(route.left), run_reference(route.right)
    choose, from_left, from_right = route.choose, route.from_left, route.from_right

    async def evaluate(item: I) -> AsyncGenerator[O]:
        match choose(item):
            case Left(a):
                async with aclosing(run_left(a)) as left_outs:
                    async for b in left_outs:
                        yield from_left(b)
            case Right(c):
                async with aclosing(run_right(c)) as right_outs:
                    async for d in right_outs:
                        yield from_right(d)
            case unknown:
                assert_never(unknown)

    return _noted(route.name, evaluate)


def _run_reference_gather[I, O, A, B, K](gather: Gather[I, O, A, B, K]) -> ItemFn[I, O]:
    """The gather's focus around the list of the body's outputs."""
    run_body = run_reference(gather.body)

    async def evaluate(a: A) -> AsyncGenerator[list[B]]:
        async with aclosing(run_body(a)) as outs:
            outputs = [b async for b in outs]
        yield outputs

    return _noted(gather.name, _focusing(gather.focus, evaluate))


def _run_reference_loop[I, O, A, B, K](loop: Loop[I, O, A, B, K]) -> ItemFn[I, O]:
    """The loop's focus around the body on the input and again on each `Left` it emits, depth-first.

    The body's output generators open at once form an explicit stack (no recursion: the depth of the
    feedback is not bounded)."""
    run_body = run_reference(loop.body)

    async def evaluate(a: A) -> AsyncGenerator[B]:
        # typed as iterators: `anext` of an async generator is typed with `Any` (a Coroutine)
        stack: list[AsyncIterator[Left[A] | Right[B]]] = [run_body(a)]
        try:
            while stack:
                try:
                    tagged = await anext(stack[-1])
                except StopAsyncIteration:  # ended, hence closed already
                    stack.pop()
                    continue
                match tagged:
                    case Left(fed_back):
                        stack.append(run_body(fed_back))
                    case Right(b):
                        yield b
                    case unknown:
                        assert_never(unknown)
        except BaseException:  # stopped early: close the open ones at once, the newest first
            for outs in reversed(stack):
                await aclose_if_closable(outs)
            raise

    return _noted(loop.name, _focusing(loop.focus, evaluate))
