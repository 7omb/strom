# Open tasks – strom

Every open task, by priority, with its ID (decisions and plans cite a task by it). **API** marks an item that adds to or
changes the public API, **Plan** one that gets a plan (skill `plan`) before code; the plan is linked here.

## P2: measurements and small performance steps

- **B10. Batched pool tasks.** A process-pool `executor.map` with chunks of 100 instead of 1 cost 1.8 instead of 117 µs
  per item. Several inputs of a `cpu_stage` per pool task changes how concurrency and metrics count tasks. **Plan**;
  worth it when process-pool throughput on cheap functions matters.

## P3: robustness

- **B11. `contextvars` in thread-pool tasks.** Pool tasks don't see the caller's context (`asyncio.to_thread` copies
  it); logging and tracing contexts are lost. Copy it at submit; also a precondition of B18.
- **B12. Cooperative cancellation after a failure.** `cancelled()` for user code, a deadline, interrupting a running
  query (sqlite's `Connection.interrupt()`, psycopg's `cancel_safe()`, safe from another thread). Signals interrupt
  processes, not threads; the prototype was left out on purpose. Until then the running pool tasks of a failed run
  finish and occupy the pool for the next run. **Plan**, **API**.
- **B13. External executors.** `FromExecutor` with Dask's `client.get_executor`, loky and mpi4py is untested against the
  real libraries: run `check_backend` with each (`uv run --frozen --with PKG`); a broken one is replaced like a
  `ThreadPoolExecutor`, also without `cancel_futures` (`tests/runtime/test_executor_backend.py`).
- **B31. A cancelled pool task under a caller nobody cancelled.** A backend that cancels its queued pool tasks when it
  closes (`FromExecutor` through `cancel_futures`, a backend of a user's) raises `CancelledError` in a step task that
  still waits; its `TaskGroup` takes that for a child that ended, so a run that outlives its pools ends without an error
  and with some of its outputs (a probe, 2026-11-13). The built-in thread and process backends raise `RuntimeError`
  there (`docs/decisions/worker-pool.md`). For every backend: `_OnBackends.cpu` and `_OnBackends.io`
  (`strom._interpreters.offloaders`) raise `RuntimeError` for a `CancelledError` of a pool task while
  `asyncio.current_task().cancelling()` is 0. With it, what the contract promises: `Backend.aclose` and the user guide
  say "cancels" for the pool tasks a close finds queued.

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
  branches of `product` and `route` but keeps each join as a separate element: fuse joins whose branches are event-loop
  only, as the reference semantics evaluates them; law rewrites (`docs/decisions/law-rewrites.md`). Not applicable: load
  shedding, reordering opaque functions, redundancy elimination, placement, fission.

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
- **B27. Wide tables of `docs/research/`.** 22 rows over 120 characters in three notes (2026-11-15:
  `docs/research/ordering.md` 13, `docs/research/durability.md` 5, `docs/research/grouping.md` 4): short facts in the
  cells, the explanations as bullets below, "Alternative | Verdict" tables as bullets. Then drop `_WIDE_TABLES` from
  `strom_tools.docs_check.doc_problems`.
- **B28. A Stop that one handler blocks while another one has a note.** The hook command prints both, and the hooks
  reference says the JSON is read beside exit code 2 (`strom_tools.hooks.hook_results`). Observe it once in a running
  session (a context summary in a turn whose stop ruff or the docs check block): whether the note shows at the blocked
  stop, and again at the next one.
- **B30. Report the checker limitations upstream** (`.claude/rules/typing.md` and the notes it lists): public issues on
  mypy, pyright and ty, so the user's step; Claude can prepare minimal reproductions.
- **B32. The findings of the review of terms and names**: `docs/plans/naming-review.md`.
- **B33. Whether the limits on the subagents hold.** No run has used the definitions with the budget of `researcher` and
  the reading by hunk of `reviewer` (`docs/decisions/subagents.md`). After the next research run and the next review,
  `bin/sessions.py tokens SESSION`: expected are under 0.3M weighted for a research run and under 0.6M for a review.
  Check one finding of the research report against its source by hand; if the report is wrong or thin, remove
  `model: sonnet`.

## Open questions for the user

- Real-time metrics tests on slow CI machines: make them robust, or keep them as they are?
- The Hypothesis profiles' `max_examples` (`tests/conftest.py`): the right trade-off of time and coverage?
- Which of the research gaps not yet listed become tasks: ordered outputs, rate limiting, the failing input on errors,
  graceful drain (`docs/research/features.md`; timeouts are in B15)?
- The rejected alternatives marked "(reason not recorded)" in `docs/decisions/`: their reasons, or whether they go
  (2026-11-15: 8 bullets in `docs/decisions/architecture.md`, `docs/decisions/benchmarks.md`,
  `docs/decisions/gather-loop.md` and `docs/decisions/test-refactoring.md`, and five names marked as not the user's
  choice). Three reasons were inferred from their context and are to confirm: the statistics of pytest-benchmark
  (`docs/decisions/benchmarks.md`), the private alias (`docs/decisions/pools-api.md`) and the OO `_JoinParts` ABC
  (`docs/decisions/product.md`).
