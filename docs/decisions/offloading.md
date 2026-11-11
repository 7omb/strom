# Offloading

A step of a streaming run reaches the pools through an `Offloader` of its own, with two operations named like the ItemFn
builders (2026-11-06): `listed` (`cpu_stage`) and `streamed` (`io_stage`); the interpreter knows no keys or workers.
What a run adds to a pool task wraps the function it gives the backend (2026-11-11), so a backend knows nothing of runs:
the guard of the run's failure flag always, the timing only when the run records, as a decorator over the pool calls
(2026-11-10), so an unmeasured run checks nothing per pool task. What `io_stage` leaves in the workers belongs to the
run's scope, released once at the run's end (2026-11-10): a step stops consuming early only when its run fails or is
cancelled, so one release covers every iterator left, whatever the reason. The module is the interpreters' (2026-11-11):
it holds run concepts (step ids, the recorder, the failure flag, the scope). How it works: `ARCHITECTURE.md`,
Concurrency and pools, and the docstrings of `strom._interpreters.offloaders` and `strom._runtime.iterator_registry`;
sources: `docs/research/backends.md` (approaches 1 and 2) and `docs/research/dependency_injection.md` (O1).

Measured, scopes and the measuring decorator (`bin/ab.py`, `BENCH_SCALE=0.5`, 9 interleaved runs each, 2026-11-10): io,
cpu, recording and event-loop rows within noise (p ≥ 0.07); `run_overhead_one_item` 1.004–1.008 (about 1.3 µs per run, p
0.001).

**Rejected**

- an `Offloader` ABC with a direct implementation for the reference semantics (`_Direct`, until 2026-11-11: the
  specification imported the runtime to learn what a leaf means, for a null object that repeated the event-loop ItemFn;
  see `reference-semantics.md`)
- three release paths (`close_unreceived` with done callbacks, `close_later`, a release of the measured offloader):
  scopes replaced them
- reference counting for the results nobody received (3.14t closed them only when the pool thread ran its next task)
- a flag the pool thread checks after opening, for the same (races with receiving the result)
- the run's failure flag for the same (misses outside cancellation and recorder errors)
- one `Pooled` per run in the run context (the failure flag referenced twice: a context with two different flags
  type-checked)
- the step id in a `ContextVar` (implicit; a branch nothing reached)
- one `RunContext` ABC for both interpreters (the reference carried an unused failure flag and measuring)
- the iterator object itself crossing to the event loop (only shared memory allows it)
- a `shares_memory` attribute on `Backend` (nothing reads it: the one capability a run needs is the type
  `StreamingBackend`)
- the registry keyed by `IteratorKey` (pyright and mypy infer its phantom type parameter invariant)
- `listed` as a plain method returning the backend's coroutine (no frame of `Pooled` per pool task; 9 runs each, the io
  rows: none significant, p 0.07–0.83)
- per worker, remembering released scopes to refuse late opens (state per run without bound, or a bounded memory that
  misses a slow open; waiting for the running tasks needs none)
- a release that waits for the running tasks in a pool thread (holds the thread; deadlocks behind queued tasks)
- a release awaited by the run (see `pools-lifecycle.md`)
- tracking the received keys in the event loop instead of scopes (the results never received still needed
  `close_unreceived`)
- `close_handle` merged into `release` (handles outlive runs: a change of its own)
- `PoolCalls` as a Protocol (both implementations are this module's; ty accepts a non-generic override of either)
- a `Run` layer per call with the affinity bound into it (an object per pool task)
- `open_iterator` returning None for an empty iterator (ty rejects `partial` of a generic function returning a union
  with None, `.claude/rules/typing.md`)
- a key never used in place of that None (2026-11-10 to 2026-11-11: a key that names nothing; `Opened` holds the items
  and an optional key)
- the next item as a bound method of the key with a dummy argument (`key.next`, 2026-11-06 to 2026-11-11: a shape for
  ty's sake, see `checker-false-positives.md`; `next_item(key)` is a function of the registry like `open_iterator`, and
  the io rows stay within noise with it: p 0.20–0.97, `bin/ab.py`, `BENCH_SCALE=0.5`, 9 interleaved runs pinned to the
  P-cores, 2026-11-11)
- a check of the flag before dispatch, on the event loop (the guard in the worker covers it: a pickled task carries the
  flag as it was at dispatch)
- a flag that pickles to a stand-in that is never set (a plain copy needs no code and skips what was dispatched after
  the failure)
