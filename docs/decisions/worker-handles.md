# Worker handles

Setup and teardown per process for blocking functions (2026-11-08): `worker_handle(open, pools)` is an `async with`
block giving a `WorkerHandle`, and `using(handle, fn)` an ordinary function of one input, so no leaf, interpreter or
pass knows handles. It means a handle per input (`with open() as h: fn(h, item)`), which is what the reference semantics
runs; the built-in backends share one per process instead, opened by its first use there and closed after the uses in
flight at the block's end. The rules a user sees: user guide, Worker handles and Failures; how it works:
`strom._runtime.worker_handles.worker_handle` and `ARCHITECTURE.md`, Concurrency and pools. Decided with it:

- on `Processes` the close is a call pinned to every worker process (2026-11-11, see `worker-pool.md`); a worker that is
  gone counts as closed;
- the lifecycle of a key is explicit states, changed in one place (`strom._runtime.worker_handles.handle_table`);
- `WorkerHandle`, `worker_handle` and `using` live in `_runtime` (they need `Pools`; `_stages` imports nothing of
  `_runtime`), `Using` itself as data in `_stages.model`;
- `using` is typed as what it gives, a function of one input (2026-11-11): the class behind it is not public.

Sources: Pekko `mapWithResource`, Beam `DoFn` setup/teardown and `Shared`, Dask worker plugins, Ray actors, SQLAlchemy
pooling guidance (one engine per process).

**Rejected**

- `Using` as a public name (until 2026-11-11: public only as the type `using` returned, which no caller has to name)
- a module-level declaration closed when the workers end (setup and teardown invisible; teardown only at the `Pools`'
  end)
- a key per `using` (two stages would hold two pools per worker)
- keying handles by the opener object (a `partial` or lambda is a new object after unpickling)
- a leaf member holding the opener (an arm in every `Leaf` dispatcher for what `__call__` says)
- `io_stage(fn, using=open)` (fn's arity depends on a keyword: overloads the checkers infer differently)
- a connection as the handle (inputs share it: transactions would mix)
- a handle per step task and run (a shared pool with a checkout per input does the same; flushing at a run's end is a
  task of its own, `docs/todo.md`)
- a handle per thread closed on its own thread (what a handle is for, an engine, a client, a model, is shared by the
  threads of a process; a thread-bound object is opened per input in `fn`, whose iterator stays on its thread)
- opening on the event loop's thread (openers block)
- opening eagerly on every worker (opens where nothing uses it)
- closing a handle after an input's error (others share it)
- `_stages.handles` (the plan's place: it would import `_runtime`)
- processes on a `ProcessPoolExecutor`, whose idle workers only a call or a signal reaches (2026-11-08 to 2026-11-11):
  the parent woke the processes holding a handle with `SIGUSR1`, and each closed it between two calls; that took closed
  keys in shared memory, opens reported as events behind a fence, a reader thread, pidfds for crashed holders and the
  retirement of an executor whose closed keys were full: the largest module of the runtime, POSIX only, a reserved
  signal
- on the way to that signal design, for its events: a `multiprocessing.Queue` (its feeder thread delays a put)
- on the way to it, to close in every worker: a `multiprocessing.Barrier` (spawns processes that never held the handle,
  stalls the pool)
- closing inside the signal handler (it runs during a running call)
- SA_RESTART instead of blocking the signal (idle workers are never woken)
- retiring the executor at every block's end (waits for every call, respawns, reloads other handles)
- `terminate_workers()`/`kill_workers()` (end the executor; SIGTERM skips `atexit`)
- a control thread via a `Manager` or `Listener` (closes off the main thread: thread-bound handles fail; a `Manager`
  costs a process, 234 ms)
- an own worker loop via `_spawn_process` (private, changed in 3.14.7)
- separate open/close callbacks or a setup/call/close class (a context manager is Python's bracket)
- a `check=` parameter, retrying openers, wrapping the user's pool (the pool's and the retry policy's jobs)
- as names of the worker-side closes of `strom.backends` (2026-11-09: `close_process_handle(key)` and
  `close_all_process_handles()`, told apart at a glance): `close_handle_here`/`close_worker` (`_here` names no scope;
  `close_worker` read as the pair of the unrelated `init_worker`)
- as those names: `close_handle`/`close_handles` (`Backend.close_handle` has that name and calls the function in each
  process)
- as those names: `close_handle_in_process`/`close_handles_in_process` (differ by one letter)
