# Worker pool

The built-in thread and process backends run on a pool of their own with addressable workers, not on executors
(2026-11-11): "on that worker, after what it runs now" is then an ordinary call (the later calls of an `io_stage`
iterator, the release of a scope, the close of a worker handle), where an executor needed a mechanism per case. A
process worker is a pool thread that forwards its calls to a child process of its own, so queued calls wait in this
process, and a cancelled one never starts on either backend. How it works: `ARCHITECTURE.md`, Concurrency and pools, and
the docstrings of `strom._runtime.pinning_pool` and `strom._runtime.process_backend`. Decided with it:

- a call without affinity prefers an idle thread that holds no iterator (the calls pinned to a holder rarely wait behind
  an unrelated one), and a busy thread takes its calls, pinned and shared, in the order they arrived;
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

**Rejected**

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
- a thread taking the calls pinned to it before any shared one (a thread with several open iterators would never take a
  shared call: starvation)
- closing silently what a pool thread still holds at its end (a missed release would pass the tests that check when an
  iterator is closed)
- the failure flag checked by the forwarding thread of a process worker (the backend would need the flag again, see
  Pools API; the copy pickled at dispatch does it)
- `check_same_thread=False` as the answer for sqlite3 (sqlite only)
- completing the caller's asyncio future from the pool thread, without a `concurrent.futures.Future` (own cancellation
  and loop-closed handling; open in `docs/todo.md`)
- worker processes that are daemons for themselves too (a function could not start a process: "daemonic processes are
  not allowed to have children")
- worker processes that are no daemons, ended by an exit function of our own (a registry of the children, a flag against
  starts during the exit, state a forked child inherits)
- failing the next pool task of a worker that ended while idle (after an interrupt in a notebook, one failed run per
  worker)
- asking whether the child lives before each call (under forkserver a selector per call)
