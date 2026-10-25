"""Focuses: how a focused step applies its leaf to an input, a join its branches, and a gather or loop its
body."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import final

type Sequenced[T] = tuple[T, int]
"""An item with its sequence number (used by `product`, `gather` and `loop` to match the items of an
input)."""


type Count = Callable[[int, int], None]
"""Adds a delta to the number of items of one input (by its sequence number) inside a `product` branch or
the body of a `gather` or `loop`."""


@final
@dataclass(frozen=True, slots=True)
class Focus[I, O, A, B, K]:
    """How a focused step applies its leaf (A -> 0..n B) to an input I (a join: its branches, A a pair; a
    gather or loop: its body).

    `split` gives the leaf's input and a kept value, `merge` combines each output with it, `finish`
    (if any) receives it when the input is handled: in a step after its last output was put (or when
    its handling stops); in a join once both branches are done with the input, possibly before the
    outputs merged last are put (a counting focus counted them in `merge` already). Plain functions:
    lifting wraps them (`first_of`, `second_of`, `counted`); runs apply them in the step's task
    loop (an unlifted step through `same_focus`) and in a join's split and merge loops."""

    split: Callable[[I], tuple[A, K]]
    merge: Callable[[B, K], O]
    finish: Callable[[K], None] | None


def same_focus[A, B]() -> Focus[A, B, A, B, None]:
    """The leaf on the whole input: how a run applies an unlifted step (one task loop for all steps)."""

    def split(item: A) -> tuple[A, None]:
        return item, None

    def merge(b: B, _: None) -> B:
        return b

    return Focus(split, merge, None)


def first_focus[A, B, X]() -> Focus[tuple[A, X], tuple[B, X], A, B, X]:
    """The leaf on the first element; each output is paired with the unchanged second one.

    Only the first element reaches the leaf (and its pool); the second stays on the event loop."""

    def split(pair: tuple[A, X]) -> tuple[A, X]:
        return pair

    def merge(b: B, x: X) -> tuple[B, X]:
        return b, x

    return Focus(split, merge, None)


def second_focus[A, B, X]() -> Focus[tuple[X, A], tuple[X, B], A, B, X]:
    """Mirror image of `first_focus`: the leaf on the second element."""

    def split(pair: tuple[X, A]) -> tuple[A, X]:
        return pair[1], pair[0]

    def merge(b: B, x: X) -> tuple[X, B]:
        return x, b

    return Focus(split, merge, None)


def counting_focus[A, B](count: Count) -> Focus[Sequenced[A], Sequenced[B], A, B, int]:
    """`first_focus` with the sequence number as the second element, counting items.

    It counts the items of each input inside a `product` branch or the body of a `gather` or `loop`: +1
    for each output before it is put downstream, -1 when the input is handled."""

    def split(item: Sequenced[A]) -> tuple[A, int]:
        return item

    def merge(b: B, sequence: int) -> Sequenced[B]:
        count(sequence, 1)
        return b, sequence

    def finish(sequence: int) -> None:
        count(sequence, -1)

    return Focus(split, merge, finish)


# Lifting a focused step or a join wraps its focus. The wrapping functions take the inner focus, so
# that it binds their type variables: pyright and ty treat type variables that no argument binds as
# `Unknown` (as in `first_focus()`), which would leave a wrong lifting unchecked there.
def first_of[I, O, A, B, K, X](inner: Focus[I, O, A, B, K]) -> Focus[tuple[I, X], tuple[O, X], A, B, tuple[K, X]]:
    """`inner` on the first element; each output is paired with the unchanged second one."""
    inner_split, inner_merge, inner_finish = inner.split, inner.merge, inner.finish

    def split(pair: tuple[I, X]) -> tuple[A, tuple[K, X]]:
        a, kept = inner_split(pair[0])
        return a, (kept, pair[1])

    def merge(b: B, kept: tuple[K, X]) -> tuple[O, X]:
        return inner_merge(b, kept[0]), kept[1]

    return Focus(split, merge, None if inner_finish is None else _finish_first(inner_finish))


def second_of[I, O, A, B, K, X](inner: Focus[I, O, A, B, K]) -> Focus[tuple[X, I], tuple[X, O], A, B, tuple[K, X]]:
    """Mirror image of `first_of`: `inner` on the second element."""
    inner_split, inner_merge, inner_finish = inner.split, inner.merge, inner.finish

    def split(pair: tuple[X, I]) -> tuple[A, tuple[K, X]]:
        a, kept = inner_split(pair[1])
        return a, (kept, pair[0])

    def merge(b: B, kept: tuple[K, X]) -> tuple[X, O]:
        return kept[1], inner_merge(b, kept[0])

    return Focus(split, merge, None if inner_finish is None else _finish_first(inner_finish))


def _finish_first[K](inner_finish: Callable[[K], None]) -> Callable[[tuple[K, object]], None]:
    """The `finish` of `first_of` and `second_of`: the inner focus's, on its kept value."""

    def finish(kept: tuple[K, object]) -> None:
        inner_finish(kept[0])

    return finish


def counted[I, O, A, B, K](
    inner: Focus[I, O, A, B, K], count: Count
) -> Focus[Sequenced[I], Sequenced[O], A, B, tuple[K, int]]:
    """`inner` on the first element of (item, sequence number) pairs, counting like `counting_focus`.

    Each output is counted after `inner` merged it; `inner` finishes first."""
    inner_split, inner_merge, inner_finish = inner.split, inner.merge, inner.finish

    def split(item: Sequenced[I]) -> tuple[A, tuple[K, int]]:
        a, kept = inner_split(item[0])
        return a, (kept, item[1])

    def merge(b: B, kept: tuple[K, int]) -> Sequenced[O]:
        out = inner_merge(b, kept[0])
        count(kept[1], 1)
        return out, kept[1]

    def finish(kept: tuple[K, int]) -> None:
        if inner_finish is not None:
            inner_finish(kept[0])
        count(kept[1], -1)

    return Focus(split, merge, finish)
