# Architecture – strom

How strom is built and the conventions for working on it: the starting point for contributors and coding agents.
Elsewhere, each once: the quick start in `README.md`; the user guide (the public API and its semantics) in the docstring
of `src/strom/__init__.py` (`python -m pydoc strom`); the terms in `GLOSSARY.md`; decisions and rejected alternatives in
`docs/decisions/` (a file per topic); open tasks in `docs/todo.md`; the working agreements and commands in `CLAUDE.md`.

## Overview

A pipeline is a value: stages are pure, typed data, built by factories (from user functions) and combinators (from
stages), composed with `|`. Interpreters give that data its meaning:

```
factories, combinators ──> Stage (data) ──> reference interpreter   evaluate: sequential, the specification
  (_stages)                                └─> streaming interpreter  runs: fused, concurrent, on asyncio
                                                (_interpreters)          ──> Pools: a backend per resource
                                                                             (_runtime; threads, processes,
                                                                             executors, your own)
```

The tests compare runs of the streaming interpreter with the reference semantics; metrics (`_metrics`) are events a run
passes to an optional recorder. Public API is exactly `__all__` of `strom` (building and running pipelines) and of the
public modules beside it, each for the users who need it: `strom.metrics`, `strom.testing` and `strom.backends`. A name
is public in one of them only; apart from `strom.testing`, they only re-export from the private packages.

## Repository

| Path | What |
| -- | -- |
| `src/strom/` | the library (packages below); `__init__.py` holds the user guide and re-exports `__all__` |
| `tests/` | one test module per library module (layout: the docstring of `tests/conftest.py`) |
| `benchmarks/benchmark.py` | pytest-benchmark benchmarks, each against a reference |
| `examples/` | runnable examples, each a uv script with its own lock that checks its results (`bin/run_examples.py`) |
| `tools/` | `strom_tools`, the development tools (Tools, below); tested in `tests/tools/` |
| `bin/` | a script per command of the tools: checks of a change and the docs, A/B benchmarks, renames, sessions |
| `docs/` | `decisions/`, `todo.md`, `plans/`, `research/` |

## Packages

The private packages of `src/strom` by role, bottom-up: each imports only from those above it (see
`docs/decisions/module-structure.md`; `tests/test_packages.py` checks it). Terms: `GLOSSARY.md`.

Module layout: packages by role (the layers below), modules inside a package by feature. A feature its consumers use (a
backend, worker handles, `Pools`) is one module, or one sub-package, holding everything only it needs (the process
backend holds its worker processes); code several features share is a module of its own, named after its concept (the
backend contract `backends`, the `iterator_registry`, the `pinning_pool`, the handle core in `worker_handles`), never a
"common" or "utils" grab-bag. New code goes into the feature it serves; when a second feature needs it, it moves out
into a module of its own. A sub-package's docstring states the import order of its modules (a slice may span several
levels of its package). Module names: Naming.

- `_validation`: value constraints
- `_closing`: closing iterators that may be closable
- `_metrics`: `events`, `stats`
- `_stages`: `model` (stages, sum tags, leaves), `display` (a stage's repr), `focus`, `lifting`, `factories`,
  `combinators`
- `_runtime` (it knows no runs, steps or metrics):
  - shared:
    - `backends`: the contract `Backend`, `StreamingBackend`, `WorkerId`; re-exported for implementers by
      `strom.backends`
    - `iterator_registry`: pool-worker side of `io_stage`: the iterator registries
    - `pinning_pool`: `PinningPool`, threads with one shared FIFO and a FIFO each (a call runs on any thread or on the
      one it is pinned to), and `Worker`, what a thread runs its calls with
    - `worker_handles`: the handle core: `handle_table` with `HandleTable`, worker handles by key; `process_handles`,
      this process's table, the thread mark `init_handles`, a handle per input in unmarked threads,
      `close_process_handle`, `close_all_process_handles`
  - a slice per backend, each with its config, composed of the shared parts (no backend inherits from another):
    - `executor_backend`: `ExecutorBackend`, `FromExecutor`; the lifetime of the user's executor
    - `thread_backend`: `ThreadBackend`, `Threads`; its worker, a thread with an iterator registry of its own
    - `process_backend`: `ProcessBackend`, `Processes`; its worker, a child process behind a pool thread, and the
      child's main function `serve`
  - on top:
    - `pools`: `Pools`, the facade, and `RunBackends`, what a run needs of it
    - `worker_handles.worker_handle`: `WorkerHandle`, `worker_handle`, `using`; `Using` itself is data in
      `_stages.model`, which the repr reads
- `_interpreters`:
  - `offloaders`: how a run uses the pools: `Offloader` over `PoolCalls` and its measuring decorator, the run's
    `FailureFlag` (with `PoolTaskSkipped`) and `RunScope`
  - `item_fns`: ItemFn builders
  - `failures`: stage notes, run errors, `RunFailed`
  - `reference`: `run_reference` (it knows no pools: a leaf's meaning does not depend on its resource)
  - `fusion`: `fused`
  - `run_context`: `RunState`, `RunContext`, the queue view `Receiver`, and `start_tasks`: the task group, the stage
    note and the end of the output stream of every element of a run
  - `steps`: a streaming step's tasks and recording, skipping pool tasks after a failure
  - `streaming`: `start_streaming`: chains, joins, routes, gathers, loops
- `_runners`: `stream`: the feeder, the run task, the outputs

A streaming run first fuses the stage (`fused`, an optimisation pass); `start_streaming` starts its tasks and returns
the queue for the run's inputs, which the runner only feeds. The reference semantics runs the stage unfused (the tests
compare with it via `strom.testing.evaluate`).

## Tools

The development tools are a package of their own, `strom_tools` in `tools/`: what the scripts in `bin/` and the Claude
Code hooks run (`.claude/hooks/dispatch.py`), each a wrapper of a few lines. It ships in no wheel, imports only the
standard library (never `strom`: the hooks run without the venv, and a tool has to work while the library is broken) and
follows the conventions below, with the library's checker settings. Its guide is the package's docstring
(`tools/strom_tools/__init__.py`): the layers and their import order, and how a tool or a hook is added.

- foundations: `tool_error` (`ToolError`, what a tool could not do), `json_objects` (JSON narrowed without `Any`)
- `workspace`: the repository as a value (`Repository`), every call of git and of make, and every process a tool starts
  (`processes`: in a group of its own that a timeout kills, its outcome a `ProcessRun`)
- the tools, which import nothing of each other: `change_checks` (skill `validate-change`), `example_scripts`,
  `docs_check`, `renames`, `sessions`, `outlines`
- entry points: `hooks` (the handlers and their dispatcher) and `commands` (one per script); only they read arguments or
  stdin, print and exit. Below them a function takes the repository, returns data and raises `ToolError`.

`tests/tools/test_structure.py` checks the imports, the layers and the wrappers (`docs/decisions/tool-package.md`).

## Design notes

What the code doesn't show at a glance. The decisions in `docs/decisions/` refer to these sections by name.

**Semantics**

- A stage maps one input to an effectful bag of outputs; every leaf is 1:0..n (a 1:1 function returns a 1-item
  iterable). A run applies a stage to each item of its inputs: the union of the bags. `|` is Kleisli composition:
  associative, `identity()` neutral (both property-tested).
- `product(f, g)` is Haskell `***`: the monoidal product (pairs every output of f with every output of g for the same
  input). Tested on both interpreters: `product(f, g) = first(f) | second(g)`, `first(f) = product(f, identity())`,
  interchange, symmetry (via `swap`) and associativity.
- A Kleisli category is only premonoidal; it is monoidal iff the effect is commutative (Power & Robinson 1997). Runs
  promise a bag, hence `first(a) | second(b) = second(b) | first(a)` for all stages, as output bags (tested).
- Laws equate output bags, not calls (see the user guide). Checked on the reference semantics (2026-11-01): with a `g`
  that drops everything, `product(f, g) | product(h, k)` never calls h, `product(f | h, g | k)` does; copying,
  `f | duplicate() = duplicate() | product(f, f)`, holds only for stages with at most one output.

**Concurrency and pools**

- Step tasks release pool capacity before putting outputs (and take inputs first, see the user guide): no deadlocks
  between steps (graphs are linear plus the bounded join).
- A run reaches its pools only through `RunBackends` (in `RunContext`, from `backends_of(pools)`), and its offloader
  knows backends only through their interface (`strom.backends`). A backend knows nothing of runs: what a run adds to a
  pool task wraps the function it passes (`strom._interpreters.offloaders`): `_guarded` skips it once the run's
  `FailureFlag` is set (a thread sees the flag, a worker in another process the copy pickled with the task), `_timed`
  measures it. Of `concurrent.futures` only `executor_backend` runs on an executor.
- The streaming interpreter sees two offloader operations, named like the ItemFn builders: `listed` (all items of a
  `cpu_stage` function in one pool task) and `streamed` (`io_stage`). `streamed` hands a list or a tuple over whole and
  keeps an iterator in its pool worker (`strom._runtime.iterator_registry`) under the run's scope (`RunScope`); the
  runner releases the scope at the run's end (`StreamingBackend.release`): one release for every iterator left, whether
  stopped early, never received or dropped after a recorder error. Measuring is a decorator over the pool calls
  (`PoolCalls`, `_Measured`). A registry holds its iterators strongly, so a missed release would leak: a pool thread
  checks at its end that its registry is empty (the close of the pools fails otherwise), a test fixture the registry of
  the process.
- The built-in workers are addressable (`PinningPool`): a pool thread takes the calls pinned to it and the unpinned ones
  in the order they arrived, so "on that worker, after what it runs now" is an ordinary call: every later call of an
  `io_stage` iterator (`affinity`), the release of a scope and the close of a worker handle (cleanups, pinned to every
  thread and never dropped: the shutdown runs those still queued). A process worker is such a thread forwarding its
  calls to a child process of its own over a pipe; the calls wait in this process, and a crash breaks one worker.
- Worker handles add no leaf: `using` returns an ordinary function (`Using`), so fusion, lifting, both interpreters and
  the offloader run it unchanged; only the backends know handles (`init_handles`, `Backend.close_handle`). Setup: the
  thread mark `init_handles` (a pool thread of `Threads`, the main thread of a worker process); teardown at the block's
  end in two phases, refuse then drain and close (`strom._runtime.worker_handles.worker_handle`). On `Processes` the
  close is the cleanup `close_process_handle`; a call is pickled when its thread takes it, so one that uses the handle
  after the refusal fails in this process, and one pickled before runs ahead of the close.
- Process backend (observed): forkserver start method; first use costs about 0.3 s once per interpreter, later `Pools`
  about 10 ms; a worker process starts at the first call of its pool thread; it imports the module of the function it
  runs (in tests: a test module or `helpers`, with pytest and hypothesis).

**Failures**

- Fail-fast follows Akka "Stop". The `in stage` note is added once per stage: a lifted join is one join.

## Conventions

**Code**

- Everything is clean in mypy strict with further error codes (the library and the tools also `disallow_any_expr` and
  `warn_unreachable`), pyright (strict except the rules in `docs/decisions/pyright-strict.md`; outside the library and
  the tools also without `reportPrivateUsage` and `reportUnknownLambdaType`), ty and ruff (the rule sets in
  `pyproject.toml`). Checker limitations: `.claude/rules/typing.md`.
- A false positive of one checker gets that checker's ignore comment on its line, with a dated entry in
  `.claude/rules/typing.md`; the code keeps the shape the other two accept. No code is shaped around a checker's bug: a
  shape stays when the bug is fixed, an ignore then fails the check.
- No `Any`. Untyped third-party API: describe the used part as a small `Protocol` (`Benchmark` in
  `benchmarks/benchmark.py`).
- No runtime type checks (the type checker's job); only value constraints types can't express.
- Privacy by namespace (PEP 8): the private packages carry the `_` (the tools are no API: none of their packages does);
  inside them, a name another library module imports has none, a name used only in its own module (or class) keeps it,
  also if tests use it. A definition used by one other module only lives there, unless it is its module's entry point or
  belongs to a family defined together (e.g. the focus algebra, the events). pyright's `reportPrivateUsage` checks it in
  `src/` and `tools/`.
- Functional style: stages are pure data, behaviour lives in module-level interpreter functions and in functions stored
  in the stages. A stage kind's only method rebuilds it (`Focused.with_focus`): it runs nothing.
- An optional feature must cost nothing when it is off.
- Terms follow `GLOSSARY.md` (one term per concept; new terms go there).
- No numbers that go stale with ordinary edits in docs, docstrings or comments (counts of lines, tests or exports;
  versions of tools or libraries). Required versions (Python) are fine, and so are measurements that say what they
  measured and when (date or commit).
- Lenses for new code and reviews: Hickey's simplicity, Elliott's denotational design; Parse don't validate; Haskell
  conduit/pipes/arrows/streamly as inspiration.

**Tests**

- Tests may test internals (`run_reference`, `run_errors`, `fused`, `pools._backends`, …); users get the small public
  API. A backend's contract is tested on every backend (`tests/runtime/test_backends.py`), with the test-only
  `PicklingBackend` standing in for a backend without shared memory.
- Never weaken an assertion to make a test pass or fast.
- Testing notes and benchmark conventions: `.claude/rules/tests.md`, `.claude/rules/benchmarks.md` and the notes of the
  areas beside them.

**Naming** (factories: see the table in the user guide)

- Modules: one concept each (a class, or closely related functions), named after it. A module built around one class has
  the class's name in snake case (`HandleTable` in `handle_table`, `Pools` in `pools`); a family of classes or functions
  defined together, the family's in the plural (`events`, `backends`, `combinators`); functions of one operation, the
  operation's (`fusion`, `lifting`). A sub-package groups the modules of one feature and is named after it.
- Leaf classes are verbs (`Expand`, `AsyncExpand`). A function building the ItemFn of a leaf is the leaf's gerund plus
  where it runs: nothing for the event loop, `_streamed` (one pool task per item) or `_listed` (all items in one pool
  task), e.g. `_expanding_streamed`. Focuses are named after what they do: `first_focus`, `counting_focus`; one wrapping
  another one after what it makes of it: `first_of`, `counted`.
- Per-kind helpers of a dispatcher: `_<dispatcher>_<kind>` with kind `step`, `focused`, `chain`, `join`, `route`,
  `gather` or `loop` (e.g. `_run_streaming_join` of `_run_streaming`): module-local, so with a `_`. Dispatchers match
  the kinds in the order `strom._stages.model` defines them (`Step`, `FocusedStep`, `Chain`, `Join`, `Route`, `Gather`,
  `Loop`); the liftings match every kind that holds a focus in one arm (`Focused`: `_lift_first_focused`). Private stage
  constructors are `_make_<thing>`.
- Closures: an ItemFn is `item_fn`, the ItemFn it wraps `inner_item_fn`, that of a focused step's leaf `leaf_item_fn`;
  in the reference interpreter, the evaluator of a part is `run_<part>` and the per-item function `evaluate`.
- Variables: `out` one output, `outs` the async generator of a step's outputs for one input, `outputs` a list of them or
  a run's outputs (the async iterator of `stream`); `stage` a stage (descriptive names such as `pairs` stay); `inputs` a
  run's inputs; `step` a `Step`, `step_id` a `StepId`, `step_stats` a `StepStats`; `pools` a `Pools`; `fn` the user's
  function. A queue ends in `q` (`inq`, `outq`, `left_inq`); task groups are `tg`, a nested one `inner_tg`; an asyncio
  task object is `<what>_task`.
- Times: a point in time ends in `_at` (`started_at`), a duration in seconds in `_time` (`busy_time`). Counts start with
  `num_` (`num_items_in`); configured sizes and limits are not counts (`cpu_workers`, `concurrency`, `buffer_size`).
- Notation: `1:1` and `1:0..n` for outputs per input.
- Type parameters: `I`/`O` input and output of a stage (`_I`/`_O` with declared variance in `Stage`, `_R` the output of
  the stage after `|`), `M` a chain's middle; `A`/`B` input and output of a leaf or wrapped ItemFn; in a join or a route
  `A -> B` the left and `C -> D` the right branch, `T` a join's kept value; in a gather or a loop `A -> B` its body (a
  loop's body emits `Left[A] | Right[B]`); `K` the kept value of a focus (also of the stages holding one), and
  `I2`/`O2`/`K2` those of the focus a stage is rebuilt with (`with_focus`); `X` a passed-through element; otherwise `T`
  an element of any type.
