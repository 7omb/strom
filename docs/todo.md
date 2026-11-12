# Open tasks – strom

Remove a task once it is done; decisions it led to go to `docs/decisions/`.

## Performance

- [ ] More passes (Hirzel et al. 2014): fuse `product` and `route` with event-loop-only branches (as the reference
  semantics evaluates them); law rewrites (see `docs/decisions/law-rewrites.md`); batch pool tasks (process-pool
  `executor.map`: 117 -> 1.8 µs per item, chunks 1 -> 100). Not applicable: load shedding, reordering opaque functions,
  redundancy elimination, placement, fission.
- [ ] Event-loop steps handle each input through an async generator (about 1.6 µs per input; runs on many inputs about
  2x slower than with a source, see `docs/decisions/runner-costs.md`): a sync path in the task loop
  (`docs/plans/event_loop_step_cost.md`).
- [ ] Backend-agnostic offloading (2026-11-05) was slower than offloading onto executors, the state before it, on some
  rows (`bin/ab.py`, `BENCH_SCALE=0.5`, 7 interleaved runs each, 2026-11-06, p < 0.05): `thread_pool_io_stage[1]`/`[5]`
  1.09/1.12, `io_stage_on_one_input` 1.05, `event_loop_steps_around_a_pool_step` 1.06–1.08, `concurrency_vs_pool_size`
  1.02–1.03, `run_overhead_new_pools[thread]` 1.16 (about 150 µs per `Pools`), `[process]` 1.04; `cpu_stage` and the
  latency rows of 2 ms tasks within noise. That state no longer exists, so these ratios cannot be measured again, and
  the built-in backends run on a pool of their own since 2026-11-11 (`docs/decisions/worker-pool.md`): compare the io
  rows with their reference rows (`thread_pool_reference_asyncio_offload_by_workers`) and profile what is left.
- [ ] Process workers start about 0.9 ms faster when the forkserver's objects are frozen (`gc.freeze()` at import of the
  main module, 2026-11-09, a probe of `ProcessBackend` run and close, 25 lifecycles × 3): a collection during a worker's
  start-up otherwise scans and copies the inherited pages, and whether one falls there depends on the object count. Try
  `gc.freeze()` first thing in a worker process (`serve`, `strom._runtime.process_backend`) and measure.
- [ ] Default `buffer_size` of steps that wait: re-measure (the old measurement was for `stage`).
- [ ] The pool threads complete a `concurrent.futures.Future` that `asyncio.wrap_future` chains to the caller's: try
  completing the asyncio future directly (fewer objects per pool task; own cancellation and loop-closed handling).

## Metrics

- [ ] OpenTelemetry recorder as optional adapter, combinable with `combine_recorders`.
- [ ] Join metrics in `product` (results waiting per branch), queue fill, event-loop lag, histograms.
- [ ] Typed hints with thresholds: `type Hint = Bottleneck | PoolOverhead`, `@final` frozen dataclasses
  `Bottleneck(step_id, utilization)` and `PoolOverhead(step_id, wait_share)` (named for what is measured: on a backend
  without shared memory the wait also holds pickling and transport), each with `__str__` giving its message;
  `diagnose(stats, *, max_utilization=0.7, max_pool_wait_share=0.3)`. Net one more public name.
- [ ] Per-worker and per-task pool metrics, with the OpenTelemetry adapter, as last fields of `PoolTaskFinished`:
  `worker: WorkerId | None` (read by `_timed` from the worker's registry, `_runtime/iterator_registry.py`) to show
  uneven remote workers; `task` to nest a pool task under its input's span (needs one offloader per task instead of per
  step occurrence).

## Features

- [ ] Error policies: retry with backoff (on top of `loop`); "resume" with a typed error output (`Left[O] | Right[E]`,
  then `route`: keeps the meaning).
- [ ] Worker handles on remote backends: an example backend implementing `Backend.close_handle` across hosts
  (`PicklingBackend` in `tests/helpers.py` implements it in one process).
- [ ] Run-bounded handles (Beam's bundles), if a case is wanted: a shard writer, a `COPY` stream or a buffered writer
  per step task, flushed at the run's end with its error failing the run. Sketch: `task_handle(open)` used with `using`,
  one per step task on "io" (a per-task ItemFn entered by `_run_step_tasks`, calls routed to the handle's thread),
  retired after an error leaving `fn`, its close awaited and never skipped at a normal end, after a failure reported to
  `loop.call_exception_handler`. The worker pool pins calls to a thread (`strom._runtime.pinning_pool`).
- [ ] "io" on processes, if wanted: a process worker is addressable like a thread (affinity, releases), so `Processes`
  could be a `StreamingBackend`; today the type checker rejects `io=Processes(...)`.
- [ ] Async openers for `async_stage` (SQLAlchemy's `async_engine.connect`, asyncpg's `pool.acquire`).
- [ ] Cross-stage and weighted limits; adaptive concurrency (SEDA).
- [ ] `aggregate(stage, fold)`, a per-input fold (batching, counting, collecting). Folds across inputs stay open:
  batching in front of an io stage needs the stream as one input (a stage making the items, run on `[None]`).

## Robustness and docs

- [ ] Propagate `contextvars` into thread-pool tasks (like `asyncio.to_thread`).
- [ ] Cooperative cancellation after a failure (`cancelled()` for user code; deadline; interrupting a running query,
  e.g. sqlite's `Connection.interrupt()` or psycopg's `cancel_safe()`, safe from another thread). Signal-based
  interruption works for processes, not threads; the prototype was explicitly left out.
- [ ] An `Interpreters(workers=)` backend config (`InterpreterPoolExecutor`; its Pydantic blocker is gone); until then
  `FromExecutor(factory=InterpreterPoolExecutor)` should work for "cpu" (untested).
- [ ] `FromExecutor` with external executors (Dask's `client.get_executor`, loky, mpi4py) is untested against the real
  libraries (an executor whose `shutdown` takes no `cancel_futures` is handled and tested); `check_backend` is the check
  to run with each. Unconfirmed: when such an executor breaks, `ExecutorBackend` drops it with
  `shutdown(wait=False, cancel_futures=True)` and no fallback, so the run would fail with `TypeError` instead of the
  `BrokenExecutor`.
- [ ] Tables of `docs/research/` with rows over 120 characters (2026-11-10: 29 rows in five files): short facts in the
  cells, the explanations as notes or bullets below; "Alternative | Verdict" tables as bullets. Then drop the
  `WIDE_TABLES` exemption of `bin/check_docs.py`.
- [ ] An example of a remote backend (`examples/`, on `multiprocessing.connection` with an `authkey`), if wanted: the
  contract is in `strom.backends`, `PicklingBackend` in `tests/helpers.py` shows one without shared memory.

## Tests and benchmarks

- [ ] No test checks `blocked_time` (removing its measurement passes every test).
- [ ] Report the checker limitations (`.claude/rules/typing.md`) upstream.
- [ ] Use ty for the static error and variance checks only: it flags all expected errors but shows `Unknown` for four
  revealed types, words messages differently and has no `--disallow-any-expr` equivalent that we know of.
- [ ] Open: make real-time metrics tests robust for CI machines? Are the profiles' `max_examples` (`tests/conftest.py`)
  the right trade-off?
- [ ] The law tests of `tests/stages/test_combinators.py` sometimes generate an example whose fan-out multiplies: nested
  `product`s and loops of the 1:3 leaves of `tests/strategies.py` (`helpers.with_depth` already allows one feedback
  only), and a law such as `interchange` composes four generated stages. A test then takes 5 to 230 s instead of 2, also
  one that only evaluates meanings (`test_gather_and_loop_laws`, 227 s; a generated stage may hold `slow_double`, 0.5 ms
  of sleep per item), on both builds, before the design review's changes and after them alike (2026-11-11: of the 19 and
  18 timed suite runs, interleaved, one took 39 s before and one 232 s after; 8079 seeded examples of one law evaluate
  in the same time on both trees, 0.4 s at most). Bound the fan-out of a generated example (its 1:n leaves, or the
  outputs per input).

## Tooling

- [ ] A Stop that one handler blocks while another one has a note (a context summary in a turn whose stop ruff or the
  docs check block): the hook command prints both, and the hooks reference says the JSON is read beside exit code 2
  (`strom_tools.hooks.hook_results`). Observe it once on a running session: whether the note shows at the blocked stop,
  and again at the next one.

- [ ] The hook command runs twice per Bash call since the PreToolUse guard (`strom_tools.hooks.command_guards`): about
  150 ms before the call (91–161 ms in five runs, 2026-11-11), 71 ms after it; Python's start-up is 35 ms, importing
  `strom_tools.hooks.dispatcher` with every handler about 100 ms (`python3 -X importtime`: `hook_events` 35 ms with what
  it imports, `docs_check` 15 ms). Try importing an event's handlers only for that event (a function per table in the
  dispatcher), against one table that shows every handler.
