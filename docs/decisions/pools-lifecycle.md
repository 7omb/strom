# Pools lifecycle

A `Pools` exists only inside its `async with` block, within one event loop; closing is final, and any later use raises,
because pools that reopened on use leaked executors nobody closed. Closing never blocks the event loop and survives a
cancelled block, and an error of one backend's close does not stop the others (how: user guide, Resources vs.
concurrency, and `strom._runtime.pools`).

Decided with it:

- A run starts the release of its scope and never awaits it. The release may wait behind a pool task that ends only
  while the pools close, so closing runs the releases still queued (`test_pools_close_runs_releases_still_queued`).
- An executor of `FromExecutor` whose `shutdown` takes no `cancel_futures` is shut down waiting; the queued tasks of
  finished runs were already cancelled with their callers.

**Rejected**

- reopening via `with` (more states)
- a `Pools` shared by several `asyncio.run` calls (needs sync creation)
- the facade running every close through `Backend.run` in separate tasks and waiting for them before closing the
  backends (deadlocks when a close waits behind a pool task that the shutdown releases)
