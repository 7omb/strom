"""Stages as data: `Stage`, the sum tags `Left` and `Right`, the leaves (and `Using`, a function of a leaf
that uses a worker handle) and the stage kinds."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterable, Callable, Iterable
from dataclasses import dataclass
from typing import Final, Generic, Literal, TypeVar, final, override

from strom._stages.focus import Focus
from strom._validation import check_positive

type Resource = Literal["cpu", "io"]


# ---------------------------------------------------------------------------- stages
# Stage declares its variance explicitly, matching its meaning (a function I -> O): contravariant
# in the input, covariant in the output. Inference (PEP 695 syntax) cannot be used: with the
# self-referential `__or__`, mypy infers invariance (or, without other members, even the flipped
# variance), and pyright infers an invariant output.
_I = TypeVar("_I", contravariant=True)
_O = TypeVar("_O", covariant=True)
_R = TypeVar("_R")
_T = TypeVar("_T", covariant=True)  # a sum tag's value; explicit: pyright infers PEP 695 tags invariant


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Stage(Generic[_I, _O]):
    """Maps each input to a bag of outputs (1:0..n), as data.

    Built by the factories (`stage`, `io_stage`, ...) and the combinators (`|`, `product`, `route`,
    `gather`, `loop`, ...); pure data, which `stream` runs."""

    name: str

    def __post_init__(self) -> None:
        if type(self) is Stage:
            raise TypeError("Stage is abstract; use the stage factories")

    def __or__(self, other: Stage[_O, _R]) -> Stage[_I, _R]:
        return Chain[_I, _O, _R](name=f"{self.name} | {other.name}", head=self, tail=other)

    @override
    def __repr__(self) -> str:
        """The name, and the settings of the parts that differ from the defaults (`strom._stages.display`).

        Not the generated dataclass repr: it showed the internal kinds, focuses and function addresses."""
        from strom._stages.display import settings as settings_of  # imported here: it matches on the kinds

        settings = settings_of(self)
        return f"<Stage {self.name!r}{f' ({"; ".join(settings)})' if settings else ''}>"


# ---- sum tags: the values of the sum type Left[A] | Right[C] that `route` takes and emits;
# `match` tells them apart (`case Left(a)`)
@final
@dataclass(frozen=True, slots=True)
class Left(Generic[_T]):
    """An item for the left branch of a `route` (its first stage), or an output of that branch."""

    value: _T


@final
@dataclass(frozen=True, slots=True)
class Right(Generic[_T]):
    """An item for the right branch of a `route` (its second stage), or an output of that branch."""

    value: _T


DEFAULT_BUFFER_SIZE: Final = 10
"""The default `buffer_size` (steps that wait, `product`) and the smallest inferred one (event-loop
steps and a run's inputs, see `strom._interpreters.streaming`)."""


DEFAULT_IN_FLIGHT: Final = 10
"""The default `concurrency` of `gather` and `loop`: inputs in flight."""


# ---- leaves: the user's function as data (where it runs); every leaf is 1:0..n
@dataclass(frozen=True, kw_only=True, eq=False)
class Expand[I, O]:
    """The items of fn(item).

    On the event loop (resource=None), streamed on the "io" pool (one pool task per item of an iterator; a
    list or a tuple whole, in one) or collected in one task on the "cpu" pool."""

    fn: Callable[[I], Iterable[O]]
    resource: Resource | None = None


@dataclass(frozen=True, kw_only=True, eq=False)
class AsyncExpand[I, O]:
    """The items of the async iterable fn(item), on the event loop.

    Also a fused group: `fn` is then composed by `fused` from consecutive event-loop steps."""

    fn: Callable[[I], AsyncIterable[O]]


type Leaf[I, O] = Expand[I, O] | AsyncExpand[I, O]
"""A closed union (not a class hierarchy): matching on it keeps I and O in all three type checkers."""


@final
@dataclass(frozen=True, slots=True, eq=False)
class Using(Generic[_I, _O]):
    """A user function that uses a worker handle (built by `using`, `strom._runtime.worker_handles.worker_handle`):
    an ordinary function of a leaf, I -> Iterable[O], that names its handle for the stage's repr.

    `call` hides the handle's type (picklable if the handle's opener and the function are)."""

    call: Callable[[_I], Iterable[_O]]
    fn_name: str
    handle_name: str

    @property
    def __name__(self) -> str:
        """The function's name: the default name of a stage of it."""
        return self.fn_name

    def __call__(self, item: _I) -> Iterable[_O]:
        return self.call(item)


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Step[I, O](Stage[I, O]):
    """One processing step: its leaf maps each input to 0..n outputs.

    concurrency: max input items of this step in flight at once (per occurrence).
    buffer_size: size of the output queue (backpressure towards this step); None (event-loop steps):
    inferred from the part that takes its outputs (see `strom._interpreters.steps`).
    """

    leaf: Leaf[I, O]
    concurrency: int = 1
    buffer_size: int | None = None

    @override
    def __post_init__(self) -> None:
        super().__post_init__()
        check_positive("concurrency", self.concurrency)
        if self.buffer_size is not None:
            check_positive("buffer_size", self.buffer_size)


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Focused[I, O, A, B, K](Stage[I, O], ABC):
    """A stage that applies its parts (A -> 0..n B) to its inputs through `focus`: a focused step, a join, a
    gather or a loop.

    Lifting such a stage wraps its focus and keeps everything else (`with_focus`), so each kind passes its
    settings on in one place, next to its fields."""

    focus: Focus[I, O, A, B, K]

    @abstractmethod
    def with_focus[I2, O2, K2](self, focus: Focus[I2, O2, A, B, K2]) -> Stage[I2, O2]:
        """This stage with `focus` in place of its own: every other field as it is.

        A method, as only a kind's own class sees the type parameters it adds to A and B; it builds data and
        runs nothing."""


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class FocusedStep[I, O, A, B, K](Focused[I, O, A, B, K]):
    """`step` applied to its inputs through `focus` (a lifted step, or a step in a `product` branch).

    It runs as one step with the settings of `step`; its name is that of `step`."""

    step: Step[A, B]

    @override
    def with_focus[I2, O2, K2](self, focus: Focus[I2, O2, A, B, K2]) -> Stage[I2, O2]:
        return FocusedStep(name=self.name, step=self.step, focus=focus)


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Chain[I, M, O](Stage[I, O]):
    """`head | tail`: the output stream of `head` is the input stream of `tail`."""

    head: Stage[I, M]
    tail: Stage[M, O]


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Join[I, O, A, B, C, D, T](Focused[I, O, tuple[A, C], tuple[B, D], T]):
    """A `product` stage: `left` and `right` applied to the pair of branch inputs through `focus`.

    For each input i: ((a, c), t) = split(i); emit merge((b, d), t) for each output b of `left` on
    a and d of `right` on c; finish(t) (if any) once both branches are done with i. `left` and
    `right` run as two independent streams. Plain `product` focuses on the whole input
    (`same_focus`); lifting wraps the focus as for a focused step; inside a branch, `finish`
    reports the input's completion to the enclosing join (see `lift_sequenced`).
    buffer_size: size of the queues into both branches and of the output queue.

    Typing: I and O are type parameters of their own, not tuples of the others, so that matching a
    Stage[I, O] keeps them in the type checkers; A to D and T stay hidden like a chain's M.
    """

    left: Stage[A, B]
    right: Stage[C, D]
    buffer_size: int = DEFAULT_BUFFER_SIZE

    @override
    def __post_init__(self) -> None:
        super().__post_init__()
        check_positive("buffer_size", self.buffer_size)

    @override
    def with_focus[I2, O2, K2](self, focus: Focus[I2, O2, tuple[A, C], tuple[B, D], K2]) -> Stage[I2, O2]:
        return Join(name=self.name, left=self.left, right=self.right, focus=focus, buffer_size=self.buffer_size)


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Route[I, O, A, B, C, D](Stage[I, O]):
    """A `route` stage: each input goes to ONE branch, `left` (A -> B) or `right` (C -> D).

    For each input i: if choose(i) is Left(a), emit from_left(b) for each output b of `left` on a;
    if it is Right(c), emit from_right(d) for each output d of `right` on c. `left` and `right` run as
    two independent streams. Plain `route` chooses by the input's tag and tags the outputs; lifting
    composes these functions and lifts both branches, so the passed-through element travels with the
    item through its branch (nothing is kept at the route, nothing is counted).
    buffer_size: size of the queues into both branches and of the output queue.

    Typing: as for `Join`, I and O are type parameters of their own.
    """

    choose: Callable[[I], Left[A] | Right[C]]
    left: Stage[A, B]
    right: Stage[C, D]
    from_left: Callable[[B], O]
    from_right: Callable[[D], O]
    buffer_size: int = DEFAULT_BUFFER_SIZE

    @override
    def __post_init__(self) -> None:
        super().__post_init__()
        check_positive("buffer_size", self.buffer_size)


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Gather[I, O, A, B, K](Focused[I, O, A, list[B], K]):
    """A `gather` stage: `body` applied to each input through `focus`, its outputs collected.

    For each input i: (a, k) = split(i); emit merge(the list of the outputs of `body` on a, k) once the
    body holds no item of i any more; then finish(k) (if any). Plain `gather` focuses on the whole input
    (`same_focus`); lifting wraps the focus as for a join.
    concurrency: max inputs in flight (taken, their list not yet put); buffer_size: size of the output
    queue.

    Typing: as for `Join`, I and O are type parameters of their own.
    """

    body: Stage[A, B]
    concurrency: int = DEFAULT_IN_FLIGHT
    buffer_size: int = DEFAULT_BUFFER_SIZE

    @override
    def __post_init__(self) -> None:
        super().__post_init__()
        check_positive("concurrency", self.concurrency)
        check_positive("buffer_size", self.buffer_size)

    @override
    def with_focus[I2, O2, K2](self, focus: Focus[I2, O2, A, list[B], K2]) -> Stage[I2, O2]:
        return Gather(
            name=self.name, body=self.body, focus=focus, concurrency=self.concurrency, buffer_size=self.buffer_size
        )


@dataclass(frozen=True, kw_only=True, eq=False, repr=False)
class Loop[I, O, A, B, K](Focused[I, O, A, B, K]):
    """A `loop` stage: `body` applied to each input through `focus`, and again to each `Left` it emits.

    For each input i: (a, k) = split(i); `body` on a, and on each a' of an output Left(a') (feedback);
    emit merge(b, k) for each output Right(b); finish(k) (if any) once the body holds no item of i any
    more. Plain `loop` focuses on the whole input (`same_focus`); lifting wraps the focus as for a
    join, so the body and its feedback are never lifted.
    concurrency: max inputs in flight (taken, not yet complete); buffer_size: size of the output queue.

    Typing: as for `Join`, I and O are type parameters of their own.
    """

    body: Stage[A, Left[A] | Right[B]]
    concurrency: int = DEFAULT_IN_FLIGHT
    buffer_size: int = DEFAULT_BUFFER_SIZE

    @override
    def __post_init__(self) -> None:
        super().__post_init__()
        check_positive("concurrency", self.concurrency)
        check_positive("buffer_size", self.buffer_size)

    @override
    def with_focus[I2, O2, K2](self, focus: Focus[I2, O2, A, B, K2]) -> Stage[I2, O2]:
        return Loop(
            name=self.name, body=self.body, focus=focus, concurrency=self.concurrency, buffer_size=self.buffer_size
        )
