# Module structure

Private packages by role, importing one way; inside a package modules by feature, each named after its one concept
(2026-11-09): a feature its consumers use is one module or sub-package with everything only it needs, and code that
several features share is a module of its own. The rules and the layout they give: `ARCHITECTURE.md`, Packages and
Naming. Decided with it:

- factories (from user functions or none: also `tag_by`, `duplicate`) apart from combinators (from stages, 2026-11-06);
- join, route, gather and loop stay in `streaming` with the dispatcher they recurse into (a module of their own would
  import it back), and `Stage.__repr__` imports `display` when called (`display` matches on the kinds);
- `RunFailed`/`run_failed` in `_interpreters.failures` (the runner and `strom.testing` both use them);
- how a run uses the pools (`offloaders`) is a module of `_interpreters` (2026-11-11): `_runtime` imports nothing of
  `_metrics` and knows no runs, and the reference semantics imports nothing of `_runtime`;
- in `_runtime` a slice per backend, named after its backend class, with its config beside it; a backend is composed of
  parts, final, and implements the contract directly: none inherits from another (2026-11-09,
  `docs/research/dependency_injection.md`, D1);
- a sub-package's `__init__` holds only a docstring (one import path per name): so `_runtime.worker_handles` spans two
  levels of `_runtime` without a cycle;
- privacy by namespace (2026-11-05; the rule: `ARCHITECTURE.md`, Conventions): a module exports a function for what
  others need from its internals (`check_open`, not the message constant), and tests import internals from their
  modules;
- classes report their module: mypy's `reveal_type`, reprs, pickles and pydoc show `strom._stages.model.Stage` (mypy's
  error messages keep `Stage`).

Precedents for the slices: `concurrent.futures` (`_base` plus a module per executor; `process` holds its whole
machinery), asyncio (`base_events` plus a module per loop flavour), anyio (`_core` plus a module per backend, 3300 lines
for asyncio in 4.16.0: why shared code stays out of the slices).

Measured: against the single module, interleaved medians 1.00 and 1.00 (2026-11-03). The backends from parts
(`bin/ab.py`, `BENCH_SCALE=0.5`, 9 interleaved runs each, 2026-11-09): io, cpu, latency and thread rows within noise (p
0.12–0.97); `run_overhead_new_pools[process]` 1.009 (p < 0.001), from where a collection falls in a new worker's
start-up, not from the code: with `gc.freeze()` in the forkserver both take 4.9 ms per first call (`docs/todo.md`,
Performance).

**Rejected**

- `ExecutorBackend` as the base class of the thread and process backends (code sharing by inheritance: the cpu-only
  backends carried the thread backend's release code, `ProcessBackend` cleared its base's `_current`, `ThreadBackend`
  was a diamond over `Backend`)
- one configurable cpu backend with an injected teardown protocol (one real implementation and a null object:
  speculative)
- injecting every part through the constructors (over-injection: what never varies, a backend builds itself)
- an `ExecutorSlot` module shared by the three backends (2026-11-09 to 2026-11-11: with the worker pool only
  `FromExecutor` runs on an executor, so its lifetime is part of `executor_backend`, without retiring executors and
  without a hook for results nobody received)
- `offloaders` in `_runtime` (until 2026-11-11: the runtime imported the events for it, and the reference semantics the
  runtime)
- the backends in one module `executor_backends` (a backend in two places, its class there and the process teardown in
  `worker_handles`; it grew with every backend)
- slice modules named after the configs (`threads`, `processes`, `from_executor`)
- packages by audience (`contract`, `builtin`: the worker-handle feature in three places)
- a `streaming` slice of `iterator_registry` with the streamed half of `offloaders` (splits the `Offloader` family;
  every streaming backend needs the registry)
- each backend owning its share of the handle core (duplicates the table or makes one backend import another; remote
  backends need it too)
- names after where code runs or what it uses (`worker`, `executors`) rather than what it holds
- `blocks` for the module of `WorkerHandle` (named after no class or concept the code uses)
- this process's handles in `handle_table` (a second concept beside the class; `iterator_registry` keeps its current
  registry, but there the registry is the concept)
- one flat module per section of the old file (the interpreter module also held lifting and fusion, the data module the
  run-time state of joins, and construction imported the interpreters)
- setting `__module__ = "strom"` (pydoc then notes `from strom._metrics.X` at every method; also on the methods: it
  would rewrite functions `dataclasses` and `typing` share with every class)
- every definition `_`-prefixed as well (two marks for one fact; `_` did not tell a name shared by five modules from a
  module-local helper; pyright's `reportPrivateUsage`, `reportUnusedClass`, `reportUnusedFunction` had to be off; the
  feared "over a hundred renames" were 50 after moving six definitions to their only user)
- `__all__` in each private module (a second list to keep in step)
- `TYPE_CHECKING` imports against cycles (moving `Sequenced` and `Resource` sufficed)
