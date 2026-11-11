"""For implementers of backends: the interface a pool runs on, and the worker side of `io_stage`.

A backend runs the pool tasks of one resource ("cpu" or "io") of a `Pools`; users choose one by passing a
callable that creates it (e.g. `Threads(workers=8)`, or a function returning a backend of your own):

    async with Pools.open_on(cpu=MyRemoteBackendConfig(...), io=Threads(workers=16)) as pools: ...

A `Backend` ("cpu" only) implements `run(fn, arg)` and `aclose()`; a `StreamingBackend` (also "io") adds
`affinity` to `run`, and `release(scope)`. Contract (see their docstrings):
  * `run` gives fn(arg) or raises what it raised, whatever they are: a run wraps its functions itself (to
    time them, and to skip them once it has failed), so a backend knows nothing of runs.
  * Pool tasks run at most once: never retry a user function; a lost worker fails the task (its error ends
    the run), and the backend may replace or reconnect its workers for later tasks.
  * Cancelling `run`'s caller cancels a queued pool task; a running one finishes (what it leaves in its
    worker, a streaming backend releases with its run's scope).
  * Without shared memory: functions, arguments, results and errors are pickled; an exception arrives as
    itself (its notes kept; the worker's traceback text as `__cause__` helps).
  * `aclose` must not block the event loop; releases still queued then run; later use raises `RuntimeError`.
  * A remote backend should compare the Python and strom versions of its workers when it connects.
Check a backend of your own with `strom.testing.check_backend` / `check_streaming_backend`.

The iterators of an `io_stage` stay in the registry of the worker that opened them, and a streaming
backend runs every call given `affinity=worker` on that worker. Workers with registries of their own call
`init_worker` once (e.g. as a thread initializer) with an id of their own; threads sharing one registry
need nothing. At its end a run calls `release(scope)`: the backend runs `release_scope(scope)` on each
registry, after the pool tasks still running on its worker (one thread per worker, in order: simply
submit it), which closes the run's iterators left there (stopped early, or opened for a cancelled caller).
The functions to run are picklable (top-level functions of strom or of the user, and partials of them): a
worker needs strom and the user's modules importable. Pickle executes code: a remote backend accepts
authenticated connections only, on a trusted network.

Worker handles (`worker_handle`, `using`) share one handle per process among the threads marked by
`init_handles`; unmarked workers open one per input. A backend whose workers are threads of this process
needs nothing more (the handle's block closes this process's handle). One whose workers run in other
processes marks them, and implements `Backend.close_handle(key)`: it runs `close_process_handle(key)` in
each of those processes (it waits there for the uses in flight and raises the close's error), and
`close_all_process_handles()` closes everything left when a worker process ends."""

from strom._runtime.backends import Backend, StreamingBackend, WorkerId
from strom._runtime.iterator_registry import init_worker, release_scope
from strom._runtime.worker_handles.process_handles import close_all_process_handles, close_process_handle, init_handles

__all__ = [
    "Backend",
    "StreamingBackend",
    "WorkerId",
    "init_worker",
    "release_scope",
    "init_handles",
    "close_process_handle",
    "close_all_process_handles",
]
