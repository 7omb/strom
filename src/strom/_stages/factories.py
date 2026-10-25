"""Factories: stages built from user functions (and the plumbing stages, which take none)."""

from collections.abc import AsyncIterable, Callable, Iterable

from strom._stages.model import DEFAULT_BUFFER_SIZE, AsyncExpand, Expand, Leaf, Left, Right, Stage, Step


def name_of(fn: object, name: str | None, default: str = "stage") -> str:
    """`name`, or else the name of `fn`: the default name of a stage built from `fn` (or of a worker handle of
    an opener)."""
    if name is not None:
        return name
    # getattr like `close_if_closable`: a value lookup, no runtime type check; objects without a
    # name (e.g. partial) get `default`
    fn_name: str = getattr(fn, "__name__", default)
    return fn_name


# Factories: see the table in the package docstring.


def _make_step[I, O](leaf: Leaf[I, O], name: str, concurrency: int = 1, buffer_size: int | None = None) -> Stage[I, O]:
    return Step(name=name, leaf=leaf, concurrency=concurrency, buffer_size=buffer_size)


# ---- stages: the items of fn(item) (1:0..n). The iterator of fn(item) is closed when the run stops
# consuming it.
def stage[I, O](fn: Callable[[I], Iterable[O]], *, name: str | None = None) -> Stage[I, O]:
    """Emits the items of fn(item) one by one, on the event loop.

    fn and its iteration must be cheap and non-blocking."""
    return _make_step(Expand(fn=fn), name_of(fn, name))


def async_stage[I, O](
    fn: Callable[[I], AsyncIterable[O]],
    *,
    concurrency: int = 1,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    name: str | None = None,
) -> Stage[I, O]:
    """Emits the items of the async iterable fn(item), on the event loop.

    fn is e.g. an async generator function."""
    return _make_step(AsyncExpand(fn=fn), name_of(fn, name), concurrency, buffer_size)


def io_stage[I, O](
    fn: Callable[[I], Iterable[O]],
    *,
    concurrency: int = 1,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    name: str | None = None,
) -> Stage[I, O]:
    """Emits the items of fn(item) as they come, on the shared "io" pool.

    fn and the iteration block (e.g. a DB cursor or a paginated API). An iterator is streamed: one pool task
    per item (the first also calls fn) plus one finding the end, all on the thread that opened it, so no
    thread is held between its items. A list or a tuple has nothing to stream and comes whole, in the one
    pool task that calls fn: a 1:1 function returns a one-item list."""
    return _make_step(Expand(fn=fn, resource="io"), name_of(fn, name), concurrency, buffer_size)


def cpu_stage[I, O](
    fn: Callable[[I], Iterable[O]],
    *,
    concurrency: int = 1,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    name: str | None = None,
) -> Stage[I, O]:
    """Emits the items of fn(item), computed on the shared "cpu" pool in ONE pool task per input.

    All items are collected there first. With a backend without shared memory (processes, the default
    of `Pools.open`), fn must be a top-level function and its input and output items picklable."""
    return _make_step(Expand(fn=fn, resource="cpu"), name_of(fn, name), concurrency, buffer_size)


def flatten[T](*, name: str = "flatten") -> Stage[Iterable[T], T]:
    """Unpacks iterable items (lists, tuples, ...): Stage[X, list[T]] | flatten() -> Stage[X, T]."""

    def unpack(item: Iterable[T]) -> Iterable[T]:
        return item

    return stage(unpack, name=name)


def where[T](pred: Callable[[T], bool], *, name: str | None = None) -> Stage[T, T]:
    """Keeps items for which the cheap, non-blocking `pred` is true, on the event loop."""

    def keep(item: T) -> Iterable[T]:
        return (item,) if pred(item) else ()

    return stage(keep, name=name_of(pred, name))


def tag_by[T](pred: Callable[[T], bool], *, name: str | None = None) -> Stage[T, Left[T] | Right[T]]:
    """Left(item) if the cheap, non-blocking `pred` is true, else Right(item), on the event loop."""

    def tag(item: T) -> Iterable[Left[T] | Right[T]]:
        return (Left(item),) if pred(item) else (Right(item),)

    return stage(tag, name=name_of(pred, name))


def identity[T](*, name: str = "identity") -> Stage[T, T]:
    """x -> x. Neutral element of `|`: identity() | s and s | identity() mean the same as s."""

    def same(item: T) -> Iterable[T]:
        return (item,)

    return stage(same, name=name)


# ---- plumbing for pairs and tags (event-loop stages, 1:1; fused with their neighbours)
def duplicate[T](*, name: str = "duplicate") -> Stage[T, tuple[T, T]]:
    """x -> (x, x). Both elements reference the SAME object: use immutable items."""

    def both(item: T) -> Iterable[tuple[T, T]]:
        return ((item, item),)

    return stage(both, name=name)


def swap[A, B](*, name: str = "swap") -> Stage[tuple[A, B], tuple[B, A]]:
    """(a, b) -> (b, a)."""

    def swapped(pair: tuple[A, B]) -> Iterable[tuple[B, A]]:
        return ((pair[1], pair[0]),)

    return stage(swapped, name=name)


def fst[A](*, name: str = "fst") -> Stage[tuple[A, object], A]:
    """(a, b) -> a."""

    def first_element(pair: tuple[A, object]) -> Iterable[A]:
        return (pair[0],)

    return stage(first_element, name=name)


def snd[B](*, name: str = "snd") -> Stage[tuple[object, B], B]:
    """(a, b) -> b."""

    def second_element(pair: tuple[object, B]) -> Iterable[B]:
        return (pair[1],)

    return stage(second_element, name=name)


def untag[T](*, name: str = "untag") -> Stage[Left[T] | Right[T], T]:
    """Left(x) -> x, Right(x) -> x: the value of either tag, e.g. after `route` (Haskell `either id id`)."""

    def value(item: Left[T] | Right[T]) -> Iterable[T]:
        match item:
            case Left(x) | Right(x):
                return (x,)

    return stage(value, name=name)
