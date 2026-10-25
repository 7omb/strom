"""Pool-worker-side helpers: the iterators of `io_stage`, kept in the worker that opened them.

Executed in pool workers (threads of this process, other processes or other hosts). Only an `IteratorKey`
crosses the boundary, never the iterator: the key names the worker whose registry holds it, and a backend
runs every later call of that key on that worker (`affinity`). `open_iterator` and `next_item` are top-level
and the key is a frozen dataclass, so the calls (a partial of the one, the other with its key) are picklable.
A list or a tuple is no iterator to keep: it has nothing to stream, so its items cross at once.

An iterator belongs to the scope of the run that opened it. It is unregistered at its end, or when its
scope is released (`release_scope`, which the backend runs on its workers at the run's end), whichever
comes first: so one release covers an iterator that its step stopped early, never received, or dropped.

A worker's registry is the one `init_worker` set up for the calling thread; without it, every thread of a
process shares the process's registry, so the threads of one pool need no routing. That process registry is
per process by design (pickled functions must find it by module path, so it cannot be passed in): every
`Pools`, run and reference evaluation of the process shares it, and its id is made at import, so processes
started by `fork` inherit it; a backend whose workers are processes calls `init_worker` in each."""

import threading
import uuid
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from itertools import count
from typing import Final, NamedTuple, cast

from strom._closing import close_if_closable
from strom._runtime.backends import WorkerId


class NextItem[O](NamedTuple):
    """An item of a registered iterator (wrapped, because the item may itself be None)."""

    item: O


_LOST = (
    "no iterator of this input on this worker: it was released with its run, lost with its worker, or the call "
    "was misrouted"
)


@dataclass(frozen=True, slots=True)
class IteratorKey[O]:
    """The iterator of one input of an `io_stage`, in the registry of `worker`; it yields O."""

    worker: WorkerId
    num: int


class _Registered[O]:
    """A registered iterator of `scope`. The lock lets the release of its scope (after a cancellation) wait
    for a `next` still running; calls of one key never overlap otherwise, as the consumer awaits each."""

    __slots__ = ("iterator", "lock", "scope")

    def __init__(self, iterator: Iterator[O], scope: str) -> None:
        self.iterator = iterator
        self.scope = scope
        self.lock = threading.Lock()

    def close(self) -> None:
        """Closes the iterator; errors of its close are ignored."""
        with self.lock, suppress(Exception):
            close_if_closable(self.iterator)


@dataclass(eq=False, slots=True)
class _Registry:
    """A worker's registry: its id and the iterators it holds."""

    id: WorkerId
    iterators: dict[int, _Registered[object]] = field(default_factory=dict)  # by `IteratorKey.num`
    nums: count[int] = field(default_factory=count)
    lock: threading.Lock = field(default_factory=threading.Lock)  # guards `iterators` (pool threads at once)


class _Local(threading.local):
    registry: _Registry | None = None  # set by `init_worker`


_PROCESS_REGISTRY: Final = _Registry(WorkerId(uuid.uuid4().hex))  # threads without `init_worker`
_local: Final = _Local()


def _current_registry() -> _Registry:
    registry = _local.registry
    return _PROCESS_REGISTRY if registry is None else registry


def init_worker(worker: WorkerId) -> None:
    """A backend's worker initializer: the calling thread gets a registry of its own, named `worker`.

    For backends that route `affinity` themselves (one registry per worker); threads of a pool that share
    one registry need no initializer. Workers that are processes call it too: a forked process would
    otherwise report its parent's process registry id."""
    _local.registry = _Registry(worker)


class Opened[O](NamedTuple):
    """What one pool task gives of fn(item): the items ready at once, and the key of its iterator if more may
    come (None: these are all, and nothing is registered)."""

    items: Sequence[O]
    key: IteratorKey[O] | None


def open_iterator[I, O](scope: str, fn: Callable[[I], Iterable[O]], item: I) -> Opened[O]:
    """fn(item) in one pool task: all its items if it is a list or a tuple, else its iterator, registered in
    this worker under `scope`, with its first item.

    A list or a tuple has nothing to stream, so it crosses whole and nothing is kept here; how the items come
    follows what the function returned (a dispatch on the representation, no check of the type). Of an
    iterator the first item is needed at once, so fetching it here holds the worker no longer. If the iterator
    ends at once or fetching fails, it is not kept (a failed first item also closes it; errors of that close
    are ignored)."""
    result = fn(item)
    match result:
        case list() | tuple():
            return Opened(result, None)
        case _:
            pass
    registry = _current_registry()
    iterator = iter(result)
    try:
        first = next(iterator)
    except StopIteration:
        return Opened((), None)
    except BaseException:
        with suppress(Exception):
            close_if_closable(iterator)
        raise
    with registry.lock:
        num = next(registry.nums)
        registry.iterators[num] = _Registered[object](iterator, scope)
    return Opened((first,), IteratorKey(registry.id, num))


def next_item[O](key: IteratorKey[O]) -> NextItem[O] | None:
    """The next item of the iterator of `key`, in one pool task on its worker; None at its end (the iterator
    is then unregistered).

    After an error the iterator stays registered until its scope is released (as after any early stop).
    Raises `LookupError` if this worker holds no iterator of the key (never None: that would end the
    stream)."""
    registry = _current_registry()
    registered = registry.iterators.get(key.num) if registry.id == key.worker else None
    if registered is None:
        raise LookupError(_LOST)
    # the registry holds iterators of every item type; the key says which one this is
    typed = cast("_Registered[O]", registered)
    with typed.lock:
        try:
            return NextItem(next(typed.iterator))
        except StopIteration:
            with registry.lock:
                registry.iterators.pop(key.num, None)
            return None


def release_scope(scope: str) -> None:
    """Closes and unregisters the iterators of `scope` (a run) that this worker's registry still holds;
    errors of their closes are ignored. Each close waits for a `next` of its iterator still running.

    A streaming backend runs it on its workers when the run ends (`StreamingBackend.release`)."""
    registry = _current_registry()
    with registry.lock:
        nums = [num for num, registered in registry.iterators.items() if registered.scope == scope]
        released = [registry.iterators.pop(num) for num in nums]
    for registered in released:
        registered.close()


def holds_iterators() -> bool:
    """Whether this worker's registry holds an iterator: later calls will then be pinned to this worker."""
    return bool(_current_registry().iterators)


def close_unreleased() -> int:
    """At a worker's end: closes and unregisters every iterator its registry still holds, and returns how many
    there were. None, unless a run's release never reached this worker (every run releases its scope at its
    end, and a backend runs the releases still queued when it closes)."""
    registry = _current_registry()
    with registry.lock:
        left = list(registry.iterators.values())
        registry.iterators.clear()
    for registered in left:
        registered.close()
    return len(left)
