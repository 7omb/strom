# Worker pool

The built-in thread and process backends run on a pool of their own with addressable workers, not on executors
(2026-11-11): "on that worker, after what it runs now" is then an ordinary call (the later calls of an `io_stage`
iterator, the release of a scope, the close of a worker handle), where an executor needed a mechanism per case. A
process worker is a pool thread that forwards its calls to a child process of its own, so queued calls wait in this
process, and a cancelled one never starts on either backend. How it works: `ARCHITECTURE.md`, Concurrency and pools, and
the docstrings of `strom._runtime.pinning_pool` and `strom._runtime.process_backend`. Decided with it:

- an unpinned call prefers an idle thread that holds no iterator (the calls pinned to a holder rarely wait behind an
  unrelated one), and a busy thread takes its calls, pinned and unpinned, in the order they arrived;
- a pool thread checks at its end that its registry is empty: a missed release fails the close of the pools instead of
  leaking;
- a worker process that ended while idle (killed, or interrupted with the user's Ctrl-C) fails nothing: it ran nothing,
  and another process takes its next call;
- a child is a daemon of its parent only: the parent ends those of a backend that was never closed, and the functions a
  worker runs may start processes (as with a `ProcessPoolExecutor`);
- one child starts at a time: under `fork`, a child started meanwhile inherited the other's end of its pipe and hid its
  death (a probe on 3.14t with 8 workers: 3 of 63 deaths unnoticed without the lock, 0 of 42 with it).

Measured against the executors (`bin/ab.py`, `BENCH_SCALE=0.3`, 7 interleaved runs pinned to the P-cores of a hybrid
CPU, 2026-11-11; B/A with p): `run_overhead_new_pools[thread]`/`[process]` 0.92/0.95 (0.064/0.002);
`process_pool_cpu_stage[1]`/`[4]` 0.29/0.58 by the medians, not significant (0.41/0.23), as the executor's runs spread
widely (an IQR of 840 and 140 µs against 13 and 34); the thread rows (`thread_pool_io_stage`, `recording`,
`concurrency_vs_pool_size`, `pool_factories`) and the two `io_one_to_many` rows of one pool task within noise. Unpinned
and before the last fixes of the pool, the process rows were 0.56/0.63 (0.035/0.004); one unpinned comparison showed
1.49 for an `io_one_to_many` row and its repetition 1.01: core placement. On the free-threaded build (a probe of 6000
items, 7 interleaved rounds, pinned): plain io pool tasks 0.96 (0.005), the items of one `io_stage` iterator 1.06
(0.002), of three at once 1.02 (0.030); with the GIL the same probe gives 0.99, 0.82 and 0.83 (0.85, 0.66, 0.002).

The pool thread hands a call's result or error to the caller's event loop, which sets it on the caller's asyncio future
(2026-11-13): a `concurrent.futures.Future` and `asyncio.wrap_future` between them cost a lock, a condition and two
callbacks per pool task. Cleanups keep their `concurrent.futures.Future`s: they are rare (a release, the close of a
worker handle). What a caller gets and which calls never run: the docstring of `PinningPool.run`; how: that of
`strom._runtime.pinning_pool`. A pool thread asks whether a call's caller still waits by reading the state of that
future, which asyncio does not promise to be safe from another thread: one read, and four threads reading `done()` while
the loop completed 200,000 futures saw no error on 3.14, with and without the GIL (a probe, no proof). Before and after
(a probe, 20,000 items of a cheap function, 5 workers and 5 callers, 9 interleaved rounds pinned to the P-cores; µs per
item, medians, with the GIL / free-threaded): awaiting `ThreadBackend.run` 48.8 → 34.2 / 13.1 → 7.2, where asyncio tasks
awaiting `loop.run_in_executor` took 48.9 / 14.0 in rounds of their own; `io_stage(inc, concurrency=5)` in a run 67.8 →
44.4 / 19.2 → 11.8. With the GIL the probe's runs are bimodal (about 20 or about 50 µs for the tasks awaiting
`loop.run_in_executor`, the same ratios in both modes). `bin/ab.py` (`BENCH_SCALE=0.3`, pinned, B/A with p): 7 runs,
`pool_factories_io_stage_on_one_input` 0.52 (0.013), `thread_pool_io_stage[1]` 0.77 (0.018),
`event_loop_steps_around_a_pool_step[2 event-loop steps before, 2 after]` 0.70 (0.018),
`recording[cpu_stage (thread backend)-StatsRecorder]` 0.34 (0.009), the other pool rows 0.73–0.98 within noise; 15 runs,
`thread_pool_io_stage[5]` 0.70 (0.003), `run_overhead_new_pools[thread]` 1.026 (0.024: about 6 µs per `Pools`),
`run_overhead_one_item` and `run_overhead_new_pools[process]` 1.00. What a run still adds to its backend, 44.4 against
34.2 µs per item with the GIL and 11.8 against 7.2 without, is the work on the event loop around the pool task: the task
loop, `Offloader.streamed`, `PoolCalls.io` and two queue puts.

**Rejected**

- cancelling the caller of a call the shutdown drops (until 2026-11-13, as `wrap_future` did): a `CancelledError` in a
  task nobody cancelled, which a `TaskGroup` takes for a child that ended; a run that outlived its pools ended without
  an error, with one of four outputs (a probe; it now fails with the `RuntimeError` of a closed backend)
- a flag that the caller's task sets when it stops waiting, for the thread that takes its call (the task sets it when it
  resumes, an event-loop iteration or more after `task.cancel()`: a call taken in between ran, in a probe with the loop
  busy for 50 ms)
- `ThreadPoolExecutor` and `ProcessPoolExecutor` behind the two backends (until 2026-11-11): they hand a call to any
  worker. The thread backend ignored `affinity` (a sqlite3 cursor in an `io_stage` generator raised `ProgrammingError`
  as soon as more iterators were open than threads) and ordered a release behind the running tasks by done callbacks of
  the tasks whose callers had left; the process backend reached its workers' main threads by signal
  (`worker-handles.md`); a queued task of a failed run could still start in a process (up to workers + 1 were dispatched
  ahead)
- one single-thread `ThreadPoolExecutor` per thread (unpinned calls queue per thread ahead of time: a call waits behind
  a long one while another thread idles)
- one single-process `ProcessPoolExecutor` per worker behind a dispatcher (a manager and a feeder thread per executor:
  550–685 against 249 µs per pool task, a probe with 8 workers and 16 callers, 2026-11-10)
- a thread taking the calls pinned to it before any unpinned one (a thread with several open iterators would never take
  an unpinned call: starvation)
- closing silently what a pool thread still holds at its end (a missed release would pass the tests that check when an
  iterator is closed)
- the failure flag checked by the forwarding thread of a process worker (the backend would need the flag again, see
  Pools API; the copy pickled at dispatch does it)
- `check_same_thread=False` as the answer for sqlite3 (sqlite only)
- a pool that knows only asyncio callers (`run` without the private `_submit` and `_Caller`): its tests, which hold
  threads by events and wait on futures from the test's thread, would all have to become async
- `_Promise` or `_Waiter` as the name of `_Caller`, the caller of a call as the pool sees it (Python has no promises,
  and JavaScript's is the side that is read; "waiter" is asyncio's word in its own sources only)
- `close` for the pool's `shutdown` (the standard library's word for a pool, `Executor.shutdown`; what a user closes is
  the backend, as the error of a later call says)
- `sequence` for a queued call's `arrival`, its number in the order of arrival (the usual name of a FIFO tie-breaker, as
  in `sched.Event`; but the glossary's sequence number is a join's and identifies an input)
- another verb than "drop" for a broken child (`_ProcessWorker._drop` in `strom._runtime.process_backend`, as
  `_reap_child`), so that "drops" would be the shutdown's word alone: `ExecutorBackend._drop` does the same with a
  broken executor, and one concept would get two verbs; "drop" is to let go of what will not be used any more, said of a
  queued call, a broken executor and a broken child, each with its object
- worker processes that are daemons for themselves too (a function could not start a process: "daemonic processes are
  not allowed to have children")
- worker processes that are no daemons, ended by an exit function of our own (a registry of the children, a flag against
  starts during the exit, state a forked child inherits)
- failing the next pool task of a worker that ended while idle (after an interrupt in a notebook, one failed run per
  worker)
- asking whether the child lives before each call (under forkserver a selector per call)
