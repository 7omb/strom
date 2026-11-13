# Backlog: every open task, by priority

Status 2026-11-13: every item checked against the code of that day.

## Requirements

- All open tasks in one place, prioritised, with suggestions for the next steps (2026-11-13).
- Items that no longer apply removed, outdated ones updated (2026-11-13).

## How to work through it

- Top to bottom within a priority; each item is one change with the checks of skill `validate-change`, and leaves
  `make check` green.
- **API** marks an item that adds to or changes the public API: it needs the user's go-ahead first (`CLAUDE.md`).
- **Plan** marks an item that gets a plan of its own (skill `plan`) before code; the plan is linked here.
- A finished item is removed here; what it decided goes to `docs/decisions/`, its measurements with it.

## Next steps

1. B2 (the plan exists; its names still match the code).
2. The measurements B5–B8 as one batch.
3. The user decides about the features (P4) and the questions under "Open questions".

## P1: correctness and the largest known costs

- **B2. Event-loop steps handle each input through an async generator.** About 1.6 µs per input; runs on many inputs
  about 2x slower than when one input makes the items (`docs/decisions/runner-costs.md`). Plan:
  `docs/plans/event_loop_step_cost.md` (its names checked 2026-11-13: `_run_step_tasks`, `_fair`, `_SKIP_BUDGET`,
  `item_fn_of`, the closing and fairness tests exist as it says).

## P2: measurements and small performance steps

- **B5. Interpreters for "cpu".** `FromExecutor(factory=InterpreterPoolExecutor)` runs a `cpu_stage` and passes
  `check_backend` (probe 2026-11-13, Python 3.14, two interpreters, the function from an importable module): add that as
  a test. Then decide whether an `Interpreters(workers=)` config is worth a public name (**API**).
- **B6. `gc.freeze()` in a worker process.** Process workers started about 0.9 ms faster with the forkserver's objects
  frozen (`gc.freeze()` at import of the main module, 2026-11-09, 25 lifecycles × 3 of `ProcessBackend` run and close):
  a collection during a worker's start-up scans and copies the inherited pages. Try it first thing in `serve`
  (`strom._runtime.process_backend`) and measure the same way.
- **B7. Default `buffer_size` of steps that wait.** `DEFAULT_BUFFER_SIZE` (`strom._stages.model`) was measured for
  `stage`, not for `io_stage`, `cpu_stage` and `async_stage`: measure those with a few sizes.
- **B8. The cost of a thread-pool io task.** Compare `test_thread_pool_io_stage` with
  `test_thread_pool_reference_asyncio_offload_by_workers` (`benchmarks/benchmark.py`) and profile the difference. The
  earlier comparisons with offloading onto executors cannot be repeated (that state is gone); the built-in backends run
  on a pool of their own since 2026-11-11 (`docs/decisions/worker-pool.md`).
- **B9. One future per pool task.** `ThreadBackend.run` and `ProcessBackend` wrap the `concurrent.futures.Future` of
  `strom._runtime.pinning_pool` with `asyncio.wrap_future`: complete the asyncio future directly from the pool thread
  (fewer objects per task; cancellation and a closed loop handled there). After B8, which shows whether it matters.
- **B10. Batched pool tasks.** A process-pool `executor.map` with chunks of 100 instead of 1 cost 1.8 instead of 117 µs
  per item. Several inputs of a `cpu_stage` per pool task changes how concurrency and metrics count tasks. **Plan**;
  worth it when process-pool throughput on cheap functions matters.

## P3: robustness

- **B11. `contextvars` in thread-pool tasks.** Pool tasks don't see the caller's context (`asyncio.to_thread` copies
  it); logging and tracing contexts are lost. Copy it at submit; also a precondition of B18.
- **B12. Cooperative cancellation after a failure.** `cancelled()` for user code, a deadline, interrupting a running
  query (sqlite's `Connection.interrupt()`, psycopg's `cancel_safe()`, safe from another thread). Signals interrupt
  processes, not threads; the prototype was left out on purpose (`docs/decisions/pool-tasks-of-a-failed-run.md`).
  **Plan**, **API**.
- **B13. External executors.** `FromExecutor` with Dask's `client.get_executor`, loky and mpi4py is untested against the
  real libraries: run `check_backend` with each (`uv run --frozen --with PKG`); a broken one is replaced like a
  `ThreadPoolExecutor`, also without `cancel_futures` (`tests/runtime/test_executor_backend.py`).

## P4: features (each **API**)

- **B14. Typed hints.** `diagnose` returns `Hint(step_id, message)` today. Instead
  `type Hint = Bottleneck | PoolOverhead`, `@final` frozen dataclasses `Bottleneck(step_id, utilization)` and
  `PoolOverhead(step_id, wait_share)` (named for what is measured: without shared memory the wait holds pickling and
  transport too), each with `__str__` giving its message;
  `diagnose(stats, *, max_utilization=0.7, max_pool_wait_share=0.3)`. Net one more public name.
- **B15. Error policies and timeouts.** Retry with backoff on top of `loop`; "resume" with a typed error output
  (`Left[O] | Right[E]`, then `route`: keeps the meaning); a timeout per input. The research names these with batching
  and ordered outputs as the gaps that block the most uses (`docs/research/features.md`). **Plan**.
- **B16. `aggregate(stage, fold)`.** A per-input fold (batching, counting, collecting) without keeping the list
  (`docs/research/grouping.md`, A3). Folds across inputs stay open: batching in front of an io stage needs the stream as
  one input (a stage making the items, run on `[None]`).
- **B17. OpenTelemetry recorder.** An optional adapter, combinable with `combine_recorders`.
- **B18. Per-worker and per-task pool metrics.** Last fields of `PoolTaskFinished`: `worker: WorkerId | None` (read by
  `_timed` in `strom._interpreters.offloaders` from the worker's registry, `strom._runtime.iterator_registry`) to show
  uneven remote workers; `task` to nest a pool task under its input's span (needs one offloader per task instead of per
  step occurrence). After B17 and B11.
- **B19. More metrics.** Join metrics in `product` (results waiting per branch), queue fill, event-loop lag, histograms.
- **B20. Async openers for `async_stage`.** SQLAlchemy's `async_engine.connect`, asyncpg's `pool.acquire`.
- **B21. More fusion and rewrites (Hirzel et al. 2014).** `fused` (`strom._interpreters.fusion`) fuses inside the
  branches of `product` and `route` but keeps each join as an element of its own: fuse joins whose branches are
  event-loop only, as the reference semantics evaluates them; law rewrites (`docs/decisions/law-rewrites.md`). Not
  applicable: load shedding, reordering opaque functions, redundancy elimination, placement, fission.

## P5: when a case asks for it

- **B22. Remote backends.** An example backend in `examples/` (on `multiprocessing.connection` with an `authkey`) that
  implements `Backend.close_handle` across hosts; the contract is in `strom.backends`, `PicklingBackend` in
  `tests/helpers.py` shows one without shared memory, in one process.
- **B23. Run-bounded handles (Beam's bundles).** A shard writer, a `COPY` stream or a buffered writer per step task,
  flushed at the run's end with its error failing the run. Sketch: `task_handle(open)` used with `using`, one per step
  task on "io" (a per-task ItemFn entered by `_run_step_tasks`, calls routed to the handle's thread), retired after an
  error leaving `fn`, its close awaited and never skipped at a normal end, after a failure reported to
  `loop.call_exception_handler`. The worker pool pins calls to a thread (`strom._runtime.pinning_pool`).
- **B24. "io" on processes.** A process worker is addressable like a thread (affinity, releases), so `Processes` could
  be a `StreamingBackend`; today the type checker rejects `io=Processes(...)`.
- **B25. Cross-stage and weighted limits; adaptive concurrency (SEDA).** Named resources were rejected for now
  (`docs/decisions/resources.md`).

## Tests, tooling and docs

- **B26. ty for the static checks.** `tests/test_typing.py` checks with mypy only. ty flags all expected errors but
  shows `Unknown` for four revealed types, words its messages differently and has no `--disallow-any-expr` equivalent
  that we know of: use it for the `rejects` checks and the variance checks only.
- **B27. Wide tables of `docs/research/`.** 29 rows over 120 characters in five files (2026-11-13: `ordering.md` 13,
  `durability.md` 5, `dependency_injection.md` 5, `grouping.md` 4, `backends.md` 2): short facts in the cells, the
  explanations as bullets below, "Alternative | Verdict" tables as bullets. Then drop `_WIDE_TABLES` from
  `strom_tools.docs_check.doc_problems`.
- **B28. A Stop that one handler blocks while another one has a note.** The hook command prints both, and the hooks
  reference says the JSON is read beside exit code 2 (`strom_tools.hooks.hook_results`). Observe it once in a running
  session (a context summary in a turn whose stop ruff or the docs check block): whether the note shows at the blocked
  stop, and again at the next one.
- **B29. A retrospective.** `.checks/friction.jsonl` holds 25 entries (2026-11-13): skill `retro`.
- **B30. Report the checker limitations upstream** (`.claude/rules/typing.md` and the notes it lists): public issues on
  mypy, pyright and ty, so the user's step; Claude can prepare minimal reproductions.

## Open questions for the user

- Real-time metrics tests on slow CI machines: make them robust, or keep them as they are?
- The Hypothesis profiles' `max_examples` (`tests/conftest.py`): the right trade-off of time and coverage?
- Which of the research gaps not yet listed become tasks: ordered outputs, rate limiting, the failing input on errors,
  graceful drain (`docs/research/features.md`; timeouts are in B15)?
