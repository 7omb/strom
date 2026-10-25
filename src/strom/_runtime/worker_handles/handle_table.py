"""`HandleTable`: worker handles by key (`strom._runtime.worker_handles.worker_handle`), each opened on its first
use and kept until it is closed; this process's table and who uses it: `strom._runtime.worker_handles.process_handles`.

Each key here is in one state (`_State`), changed only under the table's lock:

    Unopened --open--> Open --mark_closed--> Closing --close, no use in flight--> Closed
    Unopened --mark_closed--> Closed --an open in flight ends--> Closing

A use is admitted in Unopened and Open only; one admitted before the mark goes on (and an open it began
ends in Closing). Closing therefore has two phases: `mark_closed`, then `close` (waits for the uses in flight
and closes the handle if it is open)."""

import threading
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, ExitStack, contextmanager
from dataclasses import dataclass, field
from itertools import count
from typing import Final, cast, final


def closed_message(name: str) -> str:
    """The error of a use of a closed worker handle."""
    return f"worker handle {name!r} is closed"


@dataclass(frozen=True, slots=True)
class _Unopened:
    """Not open here (yet, or its opener failed)."""


@dataclass(frozen=True, slots=True)
class _Open:
    """Open here: its value and the stack that closes it; `order` orders the opens of the table."""

    value: object
    stack: ExitStack
    order: int


@dataclass(frozen=True, slots=True)
class _Closing:
    """Marked closed while open: the uses in flight go on, the close closes it once they have ended."""

    open: _Open


@dataclass(frozen=True, slots=True)
class _Closed:
    """Never used again here (a use raises)."""


type _State = _Unopened | _Open | _Closing | _Closed
_UNOPENED: Final = _Unopened()
_CLOSED: Final = _Closed()


@dataclass(eq=False, slots=True)
class _Entry:
    """A key's state, its uses in flight here, and the lock its first user opens it under."""

    unused: threading.Condition  # on the table's lock: `num_uses` dropped to 0
    state: _State = _UNOPENED
    opening: threading.Lock = field(default_factory=threading.Lock)  # the first user opens, the others wait
    num_uses: int = 0


@final
class HandleTable:
    """The worker handles of one process, by key. Thread-safe: the pool threads of a process share it.

    Closed keys are kept for the table's life (one entry per handle block that reached this process): a pool
    task pickled before the close may still arrive, and is refused by its key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, _Entry] = {}
        self._orders: Final = count()

    def _entry(self, key: str) -> _Entry:
        """Under `_lock`: the entry of `key`, created `_Unopened`."""
        entry = self._entries.get(key)
        if entry is None:
            entry = self._entries[key] = _Entry(threading.Condition(self._lock))
        return entry

    def _set(self, entry: _Entry, state: _State) -> None:
        """Under `_lock`: the one place a state changes."""
        entry.state = state

    @contextmanager
    def use[R](self, key: str, name: str, open: Callable[[], AbstractContextManager[R]]) -> Generator[R]:
        """The handle `key`, opened by `open` on its first use here (a failing opener is not kept: the next
        use opens again); counted as a use in flight until the block ends. Raises `RuntimeError` once the key
        is closed."""
        with self._lock:
            entry = self._entry(key)
            state = entry.state
            if isinstance(state, _Closing | _Closed):
                raise RuntimeError(closed_message(name))
            entry.num_uses += 1
        try:
            opened = state if isinstance(state, _Open) else self._open(entry, key, name, open)
            # the table holds handles of every type; the key says which one this is
            yield cast("R", opened.value)
        finally:
            with self._lock:
                entry.num_uses -= 1
                if entry.num_uses == 0:
                    entry.unused.notify_all()

    def _open[R](self, entry: _Entry, key: str, name: str, open: Callable[[], AbstractContextManager[R]]) -> _Open:
        with entry.opening:
            with self._lock:
                opened = _open_of(entry.state)
            if opened is not None:  # opened by the user it waited for
                return opened
            stack = ExitStack()
            value = enter_opener(stack, open, name)
            with self._lock:
                opened = _Open(value, stack, next(self._orders))
                self._set(entry, opened if isinstance(entry.state, _Unopened) else _Closing(opened))
            return opened

    def held(self) -> list[str]:
        """The keys of the handles open here, newest first."""
        with self._lock:
            opens = [
                (opened.order, key)
                for key, entry in self._entries.items()
                if (opened := _open_of(entry.state)) is not None
            ]
        return [key for _, key in sorted(opens, reverse=True)]

    def is_closed(self, key: str) -> bool:
        entry = self._entries.get(key)
        return entry is not None and isinstance(entry.state, _Closing | _Closed)

    def mark_closed(self, key: str) -> None:
        """Every later use of `key` here raises; the uses in flight go on."""
        with self._lock:
            self._mark_closed(self._entry(key))

    def _mark_closed(self, entry: _Entry) -> None:
        match entry.state:
            case _Unopened():
                self._set(entry, _CLOSED)
            case _Open() as opened:
                self._set(entry, _Closing(opened))
            case _Closing() | _Closed():
                pass

    def close(self, key: str) -> None:
        """Marks `key` closed, waits until no use of it is in flight here, and closes its handle if it is open
        here; raises the error of its `__exit__` (which gets no error).

        Several closes of a key are fine: one closes the handle, the others may return before it is closed."""
        with self._lock:
            entry = self._entry(key)
            self._mark_closed(entry)
            entry.unused.wait_for(lambda: entry.num_uses == 0)
            state = entry.state
            if not isinstance(state, _Closing):
                return  # never opened here, or another close took it
            self._set(entry, _CLOSED)
        state.open.stack.close()

    def close_all(self) -> None:
        """Closes every handle open here, newest first, each even if another one's close fails; raises an
        `ExceptionGroup` of their errors."""
        errors: list[Exception] = []
        for key in self.held():
            try:
                self.close(key)
            except Exception as error:
                errors.append(error)
        if errors:
            raise ExceptionGroup("closing the worker handles failed", errors)


def _open_of(state: _State) -> _Open | None:
    match state:
        case _Open():
            return state
        case _Closing(opened):
            return opened
        case _Unopened() | _Closed():
            return None


def enter_opener[R](stack: ExitStack, open: Callable[[], AbstractContextManager[R]], name: str) -> R:
    """`open()` entered on `stack`; its error gets a note naming the handle."""
    try:
        return stack.enter_context(open())
    except BaseException as error:
        error.add_note(f"opening its handle ({name})")
        raise
