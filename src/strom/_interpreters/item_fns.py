"""ItemFn builders: a leaf as a function from one input to an async generator of its outputs."""

from collections.abc import AsyncGenerator, AsyncIterable, Callable, Iterable
from typing import assert_never

from strom._closing import aclose_if_closable, close_if_closable
from strom._interpreters.offloaders import Offloader
from strom._stages.model import AsyncExpand, Expand, Leaf

type ItemFn[I, O] = Callable[[I], AsyncGenerator[O]]
"""Maps ONE input item to its outputs (any number)."""


# Closing the outputs of an ItemFn: an async generator that ended (exhausted or raised) is closed
# already, so the consumers of ItemFns close it only when they stop early (an exception, also
# cancellation or GeneratorExit). This avoids the cost of `aclosing` per input (see
# docs/decisions/closing-outputs.md).


# ---- ItemFn builders (every leaf is 1:0..n)
# The iterator of each fn(item) is created here, or by the offloader, and closed there (if closable) as
# soon as its consumer stops. `expanding` and `async_expanding` are also what a leaf means: the reference
# semantics builds every leaf with them, whatever its resource (`strom._interpreters.reference`).
def expanding[I, O](fn: Callable[[I], Iterable[O]]) -> ItemFn[I, O]:
    """1:0..n cheap, non-blocking function on the event loop: the items of fn(item)."""

    async def item_fn(item: I) -> AsyncGenerator[O]:
        iterator = iter(fn(item))
        try:
            for out in iterator:
                yield out
        finally:
            close_if_closable(iterator)

    return item_fn


def async_expanding[I, O](fn: Callable[[I], AsyncIterable[O]]) -> ItemFn[I, O]:
    """1:0..n on the event loop: the items of the async iterable fn(item)."""

    async def item_fn(item: I) -> AsyncGenerator[O]:
        aiterator = aiter(fn(item))
        try:
            async for out in aiterator:
                yield out
        finally:
            await aclose_if_closable(aiterator)

    return item_fn


def _expanding_streamed[I, O](fn: Callable[[I], Iterable[O]], offloader: Offloader) -> ItemFn[I, O]:
    """1:0..n blocking function on the "io" pool, streamed: one pool task per item of an iterator, a list or
    a tuple whole (`Offloader.streamed`)."""

    def item_fn(item: I) -> AsyncGenerator[O]:
        return offloader.streamed(fn, item)

    return item_fn


def _expanding_listed[I, O](fn: Callable[[I], Iterable[O]], offloader: Offloader) -> ItemFn[I, O]:
    """1:0..n blocking function on the "cpu" pool, listed: all items in ONE pool task (`Offloader.listed`).

    The items of fn(item) are collected in the pool task (works with processes), then emitted."""

    async def item_fn(item: I) -> AsyncGenerator[O]:
        for out in await offloader.listed(fn, item):
            yield out

    return item_fn


# ---- the ItemFn of a leaf in a streaming run
def item_fn_of[I, O](leaf: Leaf[I, O], offloader: Offloader) -> ItemFn[I, O]:
    """The ItemFn of a leaf for one run of one step occurrence; the resource decides where its function runs
    and how its items come (see docs/decisions/resources.md)."""
    match leaf:
        case Expand():
            match leaf.resource:
                case None:
                    return expanding(leaf.fn)
                case "io":
                    return _expanding_streamed(leaf.fn, offloader)
                case "cpu":
                    return _expanding_listed(leaf.fn, offloader)
                case unknown:
                    assert_never(unknown)
        case AsyncExpand():
            return async_expanding(leaf.fn)
    assert_never(leaf)
