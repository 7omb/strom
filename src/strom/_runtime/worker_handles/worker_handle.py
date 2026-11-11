"""Worker handles: what an opener (a context manager factory) yields, opened once per process on its first use
there and closed at the end of its `worker_handle` block; `using` makes a stage's function of one.

Meaning: `using(handle, fn)` is the function `item -> with open() as h: fn(h, item)` (the `with` lasts while
an iterator that fn returned is iterated; a list or a tuple is complete when fn returns), which the reference
semantics, the event loop and unmarked threads (`FromExecutor`) run as it is: a handle per input. Pool
threads marked by `init_handles` (`Threads`) and the worker processes of `Processes` share one handle per
process instead (`strom._runtime.worker_handles.process_handles`); outputs agree for every `fn` whose outputs
do not depend on what other inputs did to the handle.

Lifecycle of a handle block:
- setup: nothing at the block's start; each process opens the handle on its first use there (`use_handle`);
- teardown at the block's end, in two phases: refuse (the key is marked closed in this process, so later
  uses and pickling for new pool tasks raise), then drain and close (in this process after its uses in
  flight, and on every created backend by its `close_handle`), the errors raised as one group."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, Callable, Iterable, Iterator
from contextlib import AbstractAsyncContextManager, AbstractContextManager, ExitStack, asynccontextmanager
from dataclasses import dataclass, field
from functools import partial
from typing import Generic, TypeVar, final, override

from strom._runtime.pools import Pools, check_open, created_backends
from strom._runtime.worker_handles.handle_table import closed_message
from strom._runtime.worker_handles.process_handles import close_process_handle, is_closed, mark_closed, use_handle
from strom._stages.factories import name_of
from strom._stages.model import Using

# explicit variance, as `Stage`: a handle of a subtype is a handle of its supertype
_R = TypeVar("_R", covariant=True)


@final
@dataclass(frozen=True, slots=True, eq=False)
class WorkerHandle(Generic[_R]):
    """A handle that `open` yields, one per process that uses it; `worker_handle` gives it for its block.

    Its identity is `key`, the same in every process (it is pickled along); two blocks of one opener are two
    handles. Whether it is closed, this process's handle table knows; a closed handle can't be pickled (so no
    new pool task takes it)."""

    open: Callable[[], AbstractContextManager[_R]]
    name: str  # the opener's: in errors, notes and the stage's repr
    key: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def closed(self) -> bool:
        """True after the block (in the process of the block, and in workers that closed it)."""
        return is_closed(self.key)

    @override
    def __reduce__(self) -> tuple[object, ...]:
        if self.closed:
            raise RuntimeError(closed_message(self.name))
        return WorkerHandle, (self.open, self.name, self.key)

    @override
    def __repr__(self) -> str:
        return f"<WorkerHandle {self.name!r}{' (closed)' if self.closed else ''}>"


def worker_handle[R](
    open: Callable[[], AbstractContextManager[R]], pools: Pools, *, name: str | None = None
) -> AbstractAsyncContextManager[WorkerHandle[R]]:
    """A worker handle for the `async with` block, inside the block of `pools`: `open()` is entered once per
    process on its first use there (by a stage of `using(handle, fn)`), and the handle is closed in every
    process that opened it when the block ends.

    `name`: by default the opener's `__name__`. The close is awaited without blocking the event loop (also
    when the block is cancelled: then in the background) and its errors are raised as one `ExceptionGroup`,
    a note per process; `__exit__` gets no error (the block may be shared by runs)."""
    check_open(pools)
    return _handle_block(WorkerHandle(open, name_of(open, name, default="handle")), pools)


@asynccontextmanager
async def _handle_block[R](handle: WorkerHandle[R], pools: Pools) -> AsyncGenerator[WorkerHandle[R]]:
    try:
        yield handle
    finally:
        mark_closed(handle.key)  # refuse
        await asyncio.shield(_close_everywhere(handle, pools))  # drain and close


async def _close_everywhere(handle: WorkerHandle[object], pools: Pools) -> None:
    """Closes the handle here (in a helper thread, after the uses in flight) and on every created backend."""
    here, *on_backends = await asyncio.gather(
        asyncio.to_thread(close_process_handle, handle.key),
        *(backend.close_handle(handle.key) for backend in created_backends(pools)),
        return_exceptions=True,
    )
    errors: list[BaseException] = [] if here is None else [here]  # the user's own group stays whole
    for result in on_backends:
        if isinstance(result, BaseExceptionGroup):
            errors.extend(result.exceptions)  # a backend's group: one error per process
        elif result is not None:
            errors.append(result)
    if errors:
        raise BaseExceptionGroup(f"closing worker handle {handle.name!r} failed", errors)


def _on_worker[R, I, O](handle: WorkerHandle[R], fn: Callable[[R, I], Iterable[O]], item: I) -> Iterable[O]:
    """fn(h, item) with the handle h (`use_handle`). Top-level, so partials pickle.

    A list or a tuple is returned as it is, its use over when fn returns (so an `io_stage` takes one pool task
    for it, as without a handle); any other iterable is iterated within the use, which lasts until the
    iteration ends, fails or is closed."""
    with ExitStack() as stack:
        opened = stack.enter_context(use_handle(handle.key, handle.name, handle.open))
        result = fn(opened, item)
        match result:
            case list() | tuple():
                return result
            case _:
                return _within(stack.pop_all(), result)


def _within[O](use: ExitStack, items: Iterable[O]) -> Iterator[O]:
    """`items`, iterated within `use` (entered already): the use ends with the iteration. (An iterator dropped
    before its first item never enters the `with`: its use ends when the use's own generator is collected.)"""
    with use:
        yield from items


def using[R, I, O](handle: WorkerHandle[R], fn: Callable[[R, I], Iterable[O]]) -> Callable[[I], Iterable[O]]:
    """`fn` with the worker handle: a function of one input for a stage factory, e.g.
    `io_stage(using(db, rows))` with `def rows(engine: Engine, query: str) -> Iterator[Row]`.

    The stage's default name is fn's; its repr names the handle."""
    call: Callable[[I], Iterable[O]] = partial(_on_worker, handle, fn)
    return Using(call, name_of(fn, None), handle.name)
