"""Combinators: stages built from stages; tuples (arrows), sums (ArrowChoice), gathering and iteration."""

from strom._stages.factories import identity
from strom._stages.focus import Focus, same_focus
from strom._stages.lifting import lift_first, lift_second
from strom._stages.model import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_IN_FLIGHT,
    Gather,
    Join,
    Left,
    Loop,
    Right,
    Route,
    Stage,
)

# ------------------------------------------------------------- tuple combinators (arrows)
# Product semantics (Kleisli arrows of the list monad): `first` / `second` pair each output with the
# untouched element; `product` pairs each output of one branch with each output of the other.


def first[A, B, X](stage: Stage[A, B]) -> Stage[tuple[A, X], tuple[B, X]]:
    """(a, x) -> (b, x) for each output b of `stage` on a.

    Applied to every step of `stage`, so each step keeps its own concurrency, buffer size and pool."""
    return lift_first(stage)


def second[A, B, X](stage: Stage[A, B]) -> Stage[tuple[X, A], tuple[X, B]]:
    """(x, a) -> (x, b) for each output b of `stage` on a."""
    return lift_second(stage)


def product[A, B, C, D](
    f: Stage[A, B], g: Stage[C, D], *, buffer_size: int = DEFAULT_BUFFER_SIZE, name: str | None = None
) -> Stage[tuple[A, C], tuple[B, D]]:
    """(a, c) -> (b, d) for each output b of f on a and each output d of g on c.

    Takes pairs: to apply f and g to the same item, duplicate it first, `duplicate() | product(f, g)`.
    The outputs of one input are the Cartesian product of the branch outputs: f emitting [1, 2] and g
    emitting ["x", "y"] give (1, "x"), (1, "y"), (2, "x"), (2, "y"); a branch emitting nothing drops
    the input. The same outputs (as a bag) as first(f) | second(g), but f and g run as two independent streams
    at the same time, and g is called once per input, not once per output of f; every step inside
    them keeps its own concurrency and buffer size.
    buffer_size: size of the queues into both branches and of the output queue."""
    focus: Focus[tuple[A, C], tuple[B, D], tuple[A, C], tuple[B, D], None] = same_focus()
    return Join(
        name=name if name is not None else f"product({f.name}, {g.name})",
        left=f,
        right=g,
        focus=focus,
        buffer_size=buffer_size,
    )


# --------------------------------------------------------- sum combinators (ArrowChoice)
# Sum semantics (the coproduct of the category of stages): an input `Left(a)` goes to the left branch,
# `Right(c)` to the right one; each output keeps its input's tag.


def route[A, B, C, D](
    f: Stage[A, B], g: Stage[C, D], *, buffer_size: int = DEFAULT_BUFFER_SIZE, name: str | None = None
) -> Stage[Left[A] | Right[C], Left[B] | Right[D]]:
    """Left(a) -> Left(b) for each output b of f on a; Right(c) -> Right(d) for each output d of g on c.

    f and g run as two independent streams at the same time; every step inside them keeps its own
    concurrency and buffer size. buffer_size: size of the queues into both branches and of the output
    queue."""

    def choose(item: Left[A] | Right[C]) -> Left[A] | Right[C]:
        return item

    def from_left(b: B) -> Left[B] | Right[D]:
        return Left(b)

    def from_right(d: D) -> Left[B] | Right[D]:
        return Right(d)

    return Route(
        name=name if name is not None else f"route({f.name}, {g.name})",
        choose=choose,
        left=f,
        right=g,
        from_left=from_left,
        from_right=from_right,
        buffer_size=buffer_size,
    )


def left[A, B, X](
    f: Stage[A, B], *, buffer_size: int = DEFAULT_BUFFER_SIZE, name: str | None = None
) -> Stage[Left[A] | Right[X], Left[B] | Right[X]]:
    """route(f, identity()): f on `Left` items; `Right` items pass unchanged."""
    passed: Stage[X, X] = identity()
    return route(f, passed, buffer_size=buffer_size, name=name if name is not None else f"left({f.name})")


def right[C, D, X](
    g: Stage[C, D], *, buffer_size: int = DEFAULT_BUFFER_SIZE, name: str | None = None
) -> Stage[Left[X] | Right[C], Left[X] | Right[D]]:
    """route(identity(), g): g on `Right` items; `Left` items pass unchanged."""
    passed: Stage[X, X] = identity()
    return route(passed, g, buffer_size=buffer_size, name=name if name is not None else f"right({g.name})")


# ---------------------------------------------------------- gathering and iteration
# Per-input combinators: the body's items of each input are counted (as in a `product` branch), so
# that a gather knows when its list is complete and a loop when an input has left its body.


def gather[A, B](
    f: Stage[A, B],
    *,
    concurrency: int = DEFAULT_IN_FLIGHT,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    name: str | None = None,
) -> Stage[A, list[B]]:
    """a -> [b, ...]: ONE output per input, the list of all outputs of f on a ([] if none).

    The list is in no particular order; it is emitted once f holds no item of the input any more. Where
    its order counts (a test comparing it, e.g. with `strom.testing`), a following stage sorts it:
    `gather(f) | stage(in_order)`, with `def in_order(items: list[B]) -> list[list[B]]: return [sorted(items)]`.
    concurrency: max inputs in flight (taken, their list not yet put), which bounds the lists kept;
    buffer_size: size of the output queue. Every step inside f keeps its own concurrency and buffer
    size."""
    focus: Focus[A, list[B], A, list[B], None] = same_focus()
    return Gather(
        name=name if name is not None else f"gather({f.name})",
        body=f,
        focus=focus,
        concurrency=concurrency,
        buffer_size=buffer_size,
    )


def loop[A, B](
    f: Stage[A, Left[A] | Right[B]],
    *,
    concurrency: int = DEFAULT_IN_FLIGHT,
    buffer_size: int = DEFAULT_BUFFER_SIZE,
    name: str | None = None,
) -> Stage[A, B]:
    """A feedback loop: f emits Left(a') to continue with a' (f is applied to it again) and Right(b) to output b.

    a -> each b that f emits as Right(b), applied to a and again to each a' it emits as Left(a'). E.g.
    paging through an API, `loop(io_stage(fetch_page))`:

        def fetch_page(url: str) -> Iterator[Left[str] | Right[Item]]:
            page = get(url)
            yield from (Right(item) for item in page.items)  # output each item
            if page.next_url:
                yield Left(page.next_url)  # continue with the next page

    f's `Left` outputs go back into f until it emits none for an input; an input whose
    `Left`s never end never completes (like an endless source). concurrency: max inputs in flight (taken,
    with items still inside f): only their items are fed back, but f emitting more than one `Left` per
    input on average makes them grow without bound. buffer_size: size of the output queue. Every step
    inside f keeps its own concurrency and buffer size."""
    focus: Focus[A, B, A, B, None] = same_focus()
    return Loop(
        name=name if name is not None else f"loop({f.name})",
        body=f,
        focus=focus,
        concurrency=concurrency,
        buffer_size=buffer_size,
    )
