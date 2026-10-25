"""Tools for testing pipelines: the reference semantics, comparing outputs as bags; and the
contract checks of a backend of your own (`check_backend`, `check_streaming_backend`).

    assert evaluate(PIPELINE, [1, 2]) == [...]                 # sequential, deterministic, no pools
    await check_against_reference(PIPELINE, items, pools)      # AssertionError: the items that differ
    await check_streaming_backend(MyRemoteBackendConfig(...))  # AssertionError: the rule broken

A run's outputs come in no particular order; `evaluate` gives them in the order of a sequential,
depth-first evaluation, calling io and cpu functions directly (no pools, no concurrency). It fails like a
run: ONE `RunFailed` of the error, noted with the stages it passed; a run notes a fused group of
event-loop steps by its chain (`'inc | neg'`), `evaluate` the step itself (`'neg'`)."""

import asyncio
import itertools
import time
import uuid
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator
from contextlib import aclosing
from functools import partial

from strom._interpreters.failures import run_failed
from strom._interpreters.reference import run_reference
from strom._runners import stream
from strom._runtime.backends import Backend, StreamingBackend
from strom._runtime.iterator_registry import next_item, open_iterator
from strom._runtime.pools import Pools
from strom._stages.model import Stage

__all__ = [
    "evaluate",
    "evaluate_async",
    "bag",
    "check_against_reference",
    "check_backend",
    "check_streaming_backend",
]


async def evaluate_async[I, O](stage: Stage[I, O], inputs: Iterable[I]) -> list[O]:
    """`evaluate` inside a running event loop (e.g. an async test)."""
    run_stage = run_reference(stage)
    outputs: list[O] = []
    try:
        for item in inputs:  # an error of the inputs ends it too, without a stage note (as a run)
            async with aclosing(run_stage(item)) as outs:
                outputs += [out async for out in outs]
    except Exception as error:
        failure = error
    else:
        return outputs
    raise run_failed([failure])  # outside the except block: no implicit chaining (as `stream`)


def evaluate[I, O](stage: Stage[I, O], inputs: Iterable[I]) -> list[O]:
    """The reference semantics: the outputs of `stage` on each input, in order, evaluated sequentially
    (depth-first) in an event loop of its own; a run must give the same items (as a bag)."""
    return asyncio.run(evaluate_async(stage, inputs))


def bag(items: Iterable[object]) -> Counter[str]:
    """`items` as a bag (a multiset by `repr`, so unhashable items work too): compare outputs with it,
    `assert bag(outputs) == bag(expected)`, and a failing assert shows the difference.

    An item counts as a whole: a list inside it is compared in its order. The list of a `gather` comes in no
    particular order, so a stage after the gather sorts it first (see `strom.gather`)."""
    return Counter(map(repr, items))


async def check_against_reference[I](stage: Stage[I, object], inputs: Collection[I], pools: Pools) -> None:
    """Checks that a run of `stage` on `inputs` gives the same items as `evaluate` (as a bag); `AssertionError`
    names the items that differ.

    The items are compared as `bag` does, each as a whole. A run fills the list of a `gather` in another order
    than `evaluate`: a stage that emits such a list passes only if it sorts the list (see `strom.gather`).
    `inputs` is iterated twice, hence a collection."""
    async with stream(stage, inputs, pools) as outputs:
        run_bag = bag([out async for out in outputs])
    reference_bag = bag(await evaluate_async(stage, inputs))
    if run_bag != reference_bag:
        missing, extra = dict(reference_bag - run_bag), dict(run_bag - reference_bag)
        raise AssertionError(f"the run differs from the reference: missing {missing}, extra {extra} (by repr)")


# ---- the contract of a backend, for implementers (see `strom.backends`)
# The functions run on the backend are top-level here, so that workers of another process or host can
# unpickle them (they need strom importable); only what a caller observes is checked.
class _BackendCheckError(Exception):
    """The error `check_backend` lets a pool task raise: it must arrive as itself, with its notes."""


def _twice(item: int) -> int:
    return 2 * item


def _fail_noted(item: int) -> int:
    error = _BackendCheckError(f"failed on {item}")
    error.add_note("noted in the worker")
    raise error


def _three_from(item: int) -> Iterator[int]:
    yield from (item, item + 1, item + 2)


def _expect(holds: bool, rule: str) -> None:
    if not holds:
        raise AssertionError(f"backend contract: {rule}")


async def check_backend(config: Callable[[], Backend]) -> None:
    """Checks the contract of `strom.backends.Backend` on backends `config` creates (e.g. in an async test of
    a backend of your own); `AssertionError` names the first rule broken.

    Checked: a pool task's result, the user's error arriving as itself (type, message, notes), and that a
    closed backend raises `RuntimeError`. The rest of the contract (cancellation, at most once) needs a view
    into the workers that only the backend has."""
    backend = config()
    try:
        _expect(await backend.run(_twice, 21) == 42, "run(fn, arg) returns fn(arg)")
        try:
            await backend.run(_fail_noted, 1)
        except Exception as error:
            notes: list[str] | None = getattr(error, "__notes__", None)
            same = (
                type(error) is _BackendCheckError and str(error) == "failed on 1" and notes == ["noted in the worker"]
            )
            _expect(same, "fn's error arrives as itself (type, message, notes)")
        else:
            _expect(False, "run raises fn's error")
    finally:
        await backend.aclose()
    try:
        await backend.run(_twice, 1)
    except RuntimeError:
        pass
    else:
        _expect(False, "a closed backend raises RuntimeError")


async def check_streaming_backend(config: Callable[[], StreamingBackend]) -> None:
    """`check_backend`, and the contract of `strom.backends.StreamingBackend`: the iterators of `io_stage`
    are advanced on the worker that opened them (`affinity`), also when several are open at once, a call
    routed to another worker finds none (`LookupError`), `release(scope)` closes the scope's iterators (within
    `_RELEASE_TIME`), and a closed backend's `release` raises `RuntimeError`."""
    await check_backend(config)
    backend = config()
    opening = partial(open_iterator, uuid.uuid4().hex, _three_from)
    try:
        first, second = await backend.run(opening, 10), await backend.run(opening, 20)
        first_key, second_key = first.key, second.key
        if first_key is None or second_key is None:  # a generator with a first item is registered
            raise AssertionError("backend contract: run(fn, arg) returns fn(arg)")
        if first_key.worker != second_key.worker:
            try:
                await backend.run(next_item, first_key, affinity=second_key.worker)  # ty: ignore[invalid-argument-type]
            except LookupError:
                pass
            else:
                _expect(False, "a call on another worker than its key's finds no iterator (LookupError)")
        values: list[int | None] = [*first.items, *second.items]
        for _ in range(3):  # interleaved, to the end of both (which unregisters them)
            for key in (first_key, second_key):
                item = await backend.run(next_item, key, affinity=key.worker)  # ty: ignore[invalid-argument-type]
                values.append(None if item is None else item.item)
        _expect(
            values == [10, 20, 11, 21, 12, 22, None, None],
            "each call with affinity=key.worker reaches the iterator of its key",
        )
        await _check_release(backend)
    finally:
        await backend.aclose()
    try:
        backend.release(uuid.uuid4().hex)
    except RuntimeError:
        pass
    else:
        _expect(False, "a closed backend's release raises RuntimeError")


_RELEASE_TIME = 5.0  # seconds a released iterator may stay open: the release is not awaited


async def _check_release(backend: StreamingBackend) -> None:
    scope = uuid.uuid4().hex
    opened = await backend.run(partial(open_iterator, scope, itertools.count), 0)
    key = opened.key
    if key is None:  # an endless iterator is registered
        raise AssertionError("backend contract: run(fn, arg) returns fn(arg)")
    backend.release(scope)
    deadline = time.monotonic() + _RELEASE_TIME
    while time.monotonic() < deadline:
        try:
            await backend.run(next_item, key, affinity=key.worker)  # ty: ignore[invalid-argument-type]
        except LookupError:
            return
        await asyncio.sleep(0.01)  # intentional: polls for the release, which runs some time after the call
    _expect(False, f"release(scope) closes the iterators of scope (within {_RELEASE_TIME} s)")
