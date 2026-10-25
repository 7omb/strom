"""The worker handles of this process: its handle table, used by the threads marked by `init_handles`, and the
closes a backend runs in each of its worker processes (`close_process_handle`, `close_all_process_handles`).

The table is per process by design, like the iterator registry (`strom._runtime.iterator_registry`): a handle
pickled to a worker finds its entry by its key. Unmarked threads (the event loop's, `FromExecutor`'s) open a
handle per input instead. A process started by `fork` gets an empty table (the parent's handles are never used
or closed there).

Teardown has two phases: `mark_closed`, then `close_process_handle` (waits for the uses in flight and closes
the handle if it is open here). `close_all_process_handles` closes everything left when a worker process
ends."""

import os
import threading
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from typing import Final, final

from strom._runtime.worker_handles.handle_table import HandleTable, closed_message, enter_opener


@contextmanager
def _per_input[R](key: str, name: str, open: Callable[[], AbstractContextManager[R]]) -> Generator[R]:
    if is_closed(key):
        raise RuntimeError(closed_message(name))
    with ExitStack() as stack:
        yield enter_opener(stack, open, name)


@final
class _ProcessTable:
    """The handle table of this process; a child started by `fork` gets a new one."""

    def __init__(self) -> None:
        self.current = HandleTable()
        self.replaced: list[HandleTable] = []  # kept: closing the parent's handles here could end them there

    def replace(self, table: HandleTable) -> None:
        self.replaced.append(self.current)
        self.current = table


class _Local(threading.local):
    uses_handles: bool = False  # set by `init_handles`


_process_table: Final = _ProcessTable()
os.register_at_fork(after_in_child=lambda: _process_table.replace(HandleTable()))
_local: Final = _Local()


def init_handles() -> None:
    """A backend's worker initializer: the calling thread uses this process's worker handles (a handle opens
    on its first use in the process and is shared by its marked threads).

    In unmarked threads, e.g. the event loop's, a worker handle opens per input."""
    _local.uses_handles = True


def use_handle[R](key: str, name: str, open: Callable[[], AbstractContextManager[R]]) -> AbstractContextManager[R]:
    """The handle `key` for one input: this process's in a marked thread, else one opened for this input."""
    if _local.uses_handles:
        return _process_table.current.use(key, name, open)
    return _per_input(key, name, open)


def is_closed(key: str) -> bool:
    """Whether `key` is closed in this process."""
    return _process_table.current.is_closed(key)


def mark_closed(key: str) -> None:
    """Every later use of `key` in this process raises (the first phase of its close)."""
    _process_table.current.mark_closed(key)


def close_process_handle(key: str) -> None:
    """Closes the worker handle `key` in this process (on any thread): marks it closed, waits for its uses in
    flight here, closes it if it is open; raises the error of its close, with a note naming the process.

    For a backend's `close_handle` on its workers: run it in each process whose workers use handles."""
    try:
        _process_table.current.close(key)
    except Exception as error:
        error.add_note(f"in process {os.getpid()}")
        raise


def close_all_process_handles() -> None:
    """Closes every worker handle open in this process, newest first; raises an `ExceptionGroup` of their
    errors. For a backend's worker process at its end."""
    _process_table.current.close_all()
