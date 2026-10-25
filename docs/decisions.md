# Decisions and rejected alternatives – strom

Rejected alternatives stay here so they aren't re-proposed without new reasons. A section per topic holds the decision
in a few sentences (with its measurements, dated) and, under **Rejected**, one bullet per alternative with why; how the
code works is in `ARCHITECTURE.md`, the user guide and the docstrings, which the sections point to. Design-note names in
the sections (Semantics, Concurrency and pools, Failures) refer to `ARCHITECTURE.md`. Read the headings and the sections
a change touches (`grep '^## ' docs/decisions.md`).

## Architecture

Stages as data + interpreter functions (a kind's one method, `with_focus`, rebuilds it and runs nothing: see Lifting)

**Rejected**

- OO (mixes the stage and its execution)
- visitor (boilerplate)
- tagless final (needs HKT → `Any`)
- async stream functions (10× faster for cheap steps, but no introspection, lifting, reference semantics)
- threads
- frameworks

## Validation

No pydantic; frozen dataclasses with `__post_init__` checks

**Rejected**

- pydantic (dependency, blocked the interpreter backend)
- runtime type checks

## Pools API

Async only: `async with Pools.open(cpu_workers=..., io_workers=..., cpu_backend=...)`, keyword-only, its configuration
checked at the call (the warning names the caller's line), short for `Pools.using(cpu=..., io=...)` with backend configs
(user guide, Backends): frozen dataclasses whose `__call__` creates the backend on first use, so `PoolConfig` needs no
protocol and `io=Processes(...)` is a type error; only `Pools.open`/`Pools.using` construct a `Pools`; pool sizes
default to the hardware's (2026-11-06). The GIL warning only for the literal `cpu_backend="thread"` (an explicit
`Threads` for cpu is the user's choice). Names: the pool is the role, the backend what runs it; public alias
`CpuBackendKind` (callers type their backend parameter). A `Pools` shows only `open`, `using`, `config` and `closed`; a
run reaches its backends through `backends_of(pools)` (see Concurrency and pools). The interface for implementers in
`strom.backends`, apart from `__all__`, split (2026-11-06) into `Backend` (`run(fn, arg)`, `aclose`: an implementer for
"cpu" writes two methods) and `StreamingBackend` (adds what only `io_stage` needs: `affinity`, `release`). A backend
knows nothing of runs (2026-11-11): `run` gives fn(arg) or raises what it raised, and what a run adds to a pool task
wraps the function it passes (see Offloading). `strom.testing.check_backend`/`check_streaming_backend` check what a
caller can observe of the contract (picklable for other processes and hosts). `Threads` threads are named "threads" by
default (`Pools.open`: "cpu" and "io")

**Rejected**

- the run's failure flag as a keyword of `run` with a public `PoolTaskSkipped` (2026-11-05 to 2026-11-11: run policy in
  every transport; the thread backend set the flag that the contract said a backend never sets, so the same calls gave
  `PoolTaskSkipped` on threads and a result on processes; every implementer had to write the check to get it)
- a sync `with Pools.of(...)` (closing blocked the event loop)
- `Pools.open` as an `@asynccontextmanager` itself (the config checked only on entry, the warning attributed to
  `contextlib`)
- `ExecutorSpec` injection (over-complication: it only re-exposed what `cpu_backend` chose; the backend interface
  instead removes the executor, which remote workers, interpreter pools and pinned iterators need)
- a `create()` method with a `BackendConfig` protocol (one more public name)
- an overload of `Pools.open` taking backends (two ways mixed in one call)
- a capability flag for the GIL warning (only the warning would read it)
- `Pools.backend()` and `Pools.close_later()` methods (public API that only the offloaders and tests needed)
- a private alias plus `# type: ignore` in callers
- the name `Pool` (easy to confuse with `Pools`)
- the name `CpuBackend` (reads like a `Backend` subclass)
- backends as records of functions, or as Protocols in place of the two classes (`Run`, `PlacedRun`, `release`,
  `aclose`: `docs/research/backends.md`, approach 4, and `docs/research/dependency_injection.md`, D3): four public names
  for two, and an implementer's class would lose the `@override` check against a base and the default of `close_handle`

## Pools lifecycle

A `Pools` exists only inside its `async with` block, within one event loop; closing is final, and any later use raises.
Closing never blocks the event loop and survives a cancelled block, and an error of one backend's close does not stop
the others (how: user guide, Resources vs. concurrency, and `strom._runtime.pools`). A run starts the release of its
scope and never awaits it (2026-11-10): the release may wait behind a pool task that ends only while the pools close, so
closing runs the releases still queued (`test_pools_close_runs_releases_still_queued`). An executor of `FromExecutor`
whose `shutdown` takes no `cancel_futures` is shut down waiting (2026-11-06; the queued tasks of finished runs were
already cancelled with their callers)

**Rejected**

- reopening on use (leaked executors nobody closed)
- reopening via `with` (more states)
- a `Pools` shared by several `asyncio.run` calls (needs sync creation)
- the facade running every close through `Backend.run` in tasks of its own and waiting for them before closing the
  backends (deadlocks when a close waits behind a pool task that the shutdown releases)

## Worker pool

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
  the tasks whose callers had left; the process backend reached its workers' main threads by signal (Worker handles); a
  queued task of a failed run could still start in a process (up to workers + 1 were dispatched ahead)
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

## Factories

Stages per placement (the user guide's factory table); stages are 1:0..n; no sinks, no `Void`, no source factories: an
effect is a stage returning nothing (or what it did) or the consumer's code; items made by a blocking or async function
come from a stage of it on one input or from async inputs

**Rejected**

- sinks (effects are consumer code or effect stages; their concurrency is consumers in a TaskGroup)
- source factories (a second way into a run)
- separate 1:1 and flat_map factories (a `Map` type and 1:1 special cases in steps, chains, lifting and `product`)
- a streaming `cpu_stage` (iterators can't cross processes)

## Combinators

Two stages on one item: `duplicate() | product(f, g)`

**Rejected**

- a `fanout` (`&&&`) combinator (explicitly not wanted)

## Runners

One runner, async only: `async with stream(stage, inputs, pools) as outputs: async for out in outputs` (named to pair
with `run_reference`); a feeder (`_feed`) puts the inputs into the queue of the stage's first step, which
`start_streaming` returns with the outputs (2026-11-05: the runner uses none of `streaming`'s internals); the inputs
belong to the caller and are not closed; an error of the inputs ends the run like a step's (failure flag set) without a
stage note; the outputs a class (`_Outputs`, several consumers may share it; one outside the block gets `RuntimeError`);
after a failure, a consumer that waits for an output waits for the end of the block (2026-11-11): one inside the block
is cancelled meanwhile, however deep in task groups, and one outside gets its error then; folds over a whole run are the
consumer's code; costs: see Runner costs

**Rejected**

- a sync runner (a loop driven from sync code costs 24 µs per resume, or a thread changes where event-loop functions
  run)
- a runner taking a fold (the consumer's code is the fold)
- an async generator as the outputs (no two consumers; PEP 789's hazard when iterated directly)
- closing the inputs
- a waiting consumer giving the block's cancellation one loop iteration before it takes itself for one outside the block
  (until 2026-11-11: the cancellation takes an iteration per task group around the consumer, so from three groups on the
  consumer raised the `RuntimeError`, which the block then raised beside the run's error)
- an `asyncio.Event` per run for that wait (`run_overhead_one_item` 1.012 and 1.005, p 0.044 and 0.007; made by the
  first consumer that waits instead: 0.998 and 0.987, p 0.42 and 0.31; `bin/ab.py`, `BENCH_SCALE=0.5`, 15 interleaved
  runs pinned to the P-cores, 2026-11-11)

## Runner costs

Accepted for now (2026-11-05): a run whose first step is an event-loop step costs about twice as much per input as with
a source (against the last state with sources, `bin/ab.py`, 9 interleaved runs, e.g. 1 event-loop step 2.96 → 5.70 µs
per input; `async_stage`, `io_stage`, `product(stage, stage)` 0.98–1.05): the step handles each input with an async
generator (1.80 vs 0.18 µs per input for iterating the result directly). `stream` adds 1–3% per input for the cheap rows
(async iteration of the outputs) and about 42 µs per run (its task group, run task and future). Measurements and the
fix: `docs/plans/event_loop_step_cost.md`

**Rejected**

- an internal source-like step in the runner fused with the stage's first steps (fixes only the first step of a run; its
  name in group names and stage notes)

## Inputs

`Iterable[I] | AsyncIterable[I]`; the feeder dispatches on the protocol once per run (`case AsyncIterable()`), an object
with both is iterated async; a dispatch on the protocol, not a value check; mypy, pyright and ty infer `I` from both and
reject inputs of another type (2026-11-05)

**Rejected**

- sync inputs only (async producers would need the `[None]` trick; nested runs fail)

## Closing check

`getattr` of `close`/`aclose` (`close_if_closable`; typed `Any | None`, accepted by `--disallow-any-expr`)

**Rejected**

- the runtime-checkable Protocol check per item (about 2.3 µs when it fails, e.g. tuple iterators)
- a per-type cache of that check (strong references to every type seen)
- `isinstance(…, Generator)` (files and other closable iterators would no longer be closed)

## `io_stage` items

An iterator: one pool task per item, the first also calling fn, plus one finding the end (`_opened`: 1:1 `io_stage` c=4
100–134 → 70–71 µs per item; about 41 µs vs 1.35 µs per cheap item collected first). A list or a tuple (2026-11-11):
whole, in the one pool task that calls fn, with nothing registered (`open_iterator`, a dispatch on what the function
returned, like the feeder's on `AsyncIterable`): it has nothing to stream, so how the items come follows the value, not
only the resource. `using` keeps the shape (a list's use of its handle ends when fn returns). Measured (2026-11-11,
recorded runs, machine not idle): the 1000 items of one list in 1001 pool tasks and 160 ms before, one pool task and
about 5 ms after; a 1:1 function returning a one-item list takes one pool task per input instead of two. Users batch
lazy iterators themselves if needed

**Rejected**

- fixed batches (latency for slow iterators)
- time-limited batches (more code, two constants)
- every in-memory collection whole (`Collection`, `Sequence`: a lazy one, such as a query set, would be iterated on the
  event loop; a subclass of list or tuple is taken for what it is)
- a delivery parameter on the factories (see Resources)

## Closing outputs

Consumers of an ItemFn close its generator only when they stop early (`except BaseException`); an ended async generator
is closed already

**Rejected**

- `aclosing` per input (A/B, 15 processes per variant: 6 inline steps 11.70 → 8.75 µs per item, `first(stage)` 3.87 →
  2.98, `product(stage, stage)` 10.62 → 8.76)

## Offloading

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
  see Reference semantics)
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
- a release awaited by the run (see Pools lifecycle)
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
  ty's sake, see Checker false positives; `next_item(key)` is a function of the registry like `open_iterator`, and the
  io rows stay within noise with it: p 0.20–0.97, `bin/ab.py`, `BENCH_SCALE=0.5`, 9 interleaved runs pinned to the
  P-cores, 2026-11-11)
- a check of the flag before dispatch, on the event loop (the guard in the worker covers it: a pickled task carries the
  flag as it was at dispatch)
- a flag that pickles to a stand-in that is never set (a plain copy needs no code and skips what was dispatched after
  the failure)

## Reference semantics

`run_reference` builds an ItemFn: lazy, depth-first; `evaluate` fails like a run (2026-11-05): ONE `RunFailed`
(`run_failed`, shared with the runner), the stage notes of a run (`stage_note`, shared; `_noted` around steps, joins,
routes, gathers and loops, not chains), except that the reference runs unfused and so names the step of a fused group,
not its chain. It knows no pools (2026-11-11): a leaf means the items of its function, lazily, whatever its resource
(`expanding`, `async_expanding`); where a function runs and how its items are delivered is a run's business

**Rejected**

- lists per chain part (diverged on endless sources, met other errors than runs)
- pool leaves through an offloader of its own (`item_fn_of(leaf, _DIRECT)`, until 2026-11-11: the reference imported the
  runtime for it, and its "cpu" leaf listed the items first, a difference no test could see: with every `Expand`
  evaluated as an event-loop leaf the suite passed unchanged)

## Stage encoding

Initial encoding: steps hold a `Leaf` (the user's function as data: what it maps to, where it runs); lifted and branch
steps are `FocusedStep`s (a step plus a `Focus`: `split`/`merge`/`finish`, composed by lifting, applied in the one task
loop, unlifted steps through `same_focus`; `_focusing` serves the reference semantics); joins hold branches plus a
`Focus` onto the pair of branch inputs (plain `product`: `same_focus`)

**Rejected**

- a join's own `split`/`merge`/`finish` (a second encoding of the focus: one hand-written rewrite per lifting)
- final encoding as a record of interpretations (pyright rejects the rank-2 lifting field; new interpreters would edit
  every constructor; opaque)
- object algebras/tagless final (need HKT)
- typed-port graph (types erased inside)
- join as a tagged linear stream (branches share queues and slots: latency f + g)
- right-nested chain and a pure `_Arr` node (no benefit without fusion; a fusion pass can flatten the tree itself)
- `adapt` closures on the leaf's ItemFn (one async generator per lifting level: A/B `first(stage)` 2.96 → 2.41 µs per
  item, `first³` 4.57 → 2.97, `product(stage, stage)` 8.79 → 7.81 with the focus in the loop)
- one wrapper generator per focused step (no gain at depth 1)

## Lifting

Typed lift functions pushed down onto steps; a join lifts by wrapping its focus (no nested join; about 35% faster for
`first(product(stage, stage))` in the sandbox); the wrappers of lifted focused steps and joins (`first_of`, `second_of`,
`counted`) take the inner focus, so that all three checkers check a lifting. Every kind that holds a focus (a focused
step, a join, a gather, a loop) is a `Focused` and rebuilds itself around another focus (`with_focus`, 2026-11-11), so a
lifting has one arm and one helper for them, and a kind passes its settings on in one place, next to its fields. A
method, although behaviour otherwise lives in functions (Architecture): it builds data and runs nothing, and only an
override sees the type parameters its kind adds; all three checkers accept it and reject a wrong lifting

**Rejected**

- a helper per kind and lifting (twelve, until 2026-11-11), each passing every setting on by hand: dropping
  `concurrency` or `buffer_size` in four of them passed the whole suite; `test_lifting_keeps_every_setting` now checks
  it for every lifting
- one function rebuilding any focused kind by `match` (the checkers lose the relation between a kind's own type
  parameters and those of its focus)
- `dataclasses.replace` for the rebuilding (it keeps the type of its argument: a cast)
- composing argument-less focuses with `_composed` (a wrong lifting was caught by mypy only, see
  `.claude/rules/typing.md`)
- one parametrised `_lift` (needed `Any`; re-examined 2026-11-06: the three liftings differ in the type function from I
  to their input type, which Python cannot express without `Any` or casts)
- `second` via `swap` (overhead)
- `first(m) = product(m, identity())` for Maps (5× slower, loses step overlap)

## `product`

All stages; two independent streams joined by sequence numbers (`lift_sequenced`), every branch step counted, one count
per branch: a branch's results of an input are kept only while the other branch is not done with it, and each pair is
merged when it can be put (in flight: the output queue's capacity and one pair) (see Concurrency and pools)

**Rejected**

- merging all pairs of a result before putting them (a late result meeting 100,000 stored ones peaked at 11.2 instead of
  4.1 MB, 2026-11-01)
- indexing the input pair (a non-pair input was silently cut to two elements; unpacking raises in both interpreters)
- one count for both branches (kept every result until the input was complete: 100,000 of 100,000 left outputs of one
  input, 2026-11-01)
- Maps only (1:1 special cases throughout)
- skipping the count for 1:1 steps (needs 1:1 detection; counting costs about 1.3 µs per branch step and item)
- per-item evaluation (slower)
- `first(f) | second(g)` (latency f + g)
- position-based matching (wrong with a concurrency above 1)
- an OO `_JoinParts` ABC
- `product(J, identity())` lifting (endless recursion)

## Metrics check

`recorder=None` is off, checked once per run; ONE task loop for all steps, recording under local `if recording` checks
(no clock reads, no events when off). Cost of recording with a `StatsRecorder`, one fused step per input (2026-11-06,
`bin/ab.py -- -k recording`, 9 runs each): 3.6 µs before the events of `InputHandled`, 4.0 µs with them (recorded rows
+2.2% and +4.7% for `product`, p ≤ 0.003; unrecorded rows unchanged, p 0.45 and 0.97)

**Rejected**

- an `Enabled` token from `enabled()` (forgeable, accepted by any recorder, unused by them; `NoRecorder` had only dead
  methods)
- always calling a no-op recorder (0.28 µs per item and step)
- separate loops per variant (duplicated; hand-specialised loops were 2–7% faster unrecorded, 15% slower recorded for
  lifted steps)
- variants generated from one template by pruning its AST (needs `inspect.getsource` at run time; hidden machinery)
- unlifted steps without a focus (`None`: two type escapes)

## Queue access

`put_nowait`/`get_nowait` when no wait is needed (asyncio's `put`/`get` don't yield then either, see anyio's `send`), in
steps and in a join's loops; only puts that wait count as blocked

**Rejected**

- awaiting `put`/`get` per item (a coroutine each: about 9% of 6 inline steps)

## Run errors

A failed run always raises ONE `ExceptionGroup` ("pipeline run failed") of the errors `failing` recorded, as raised (a
user's own group stays whole), the run's TaskGroup nesting removed; KeyboardInterrupt/SystemExit unwrapped; strict like
asyncio's TaskGroup, anyio and Trio >= 0.25 (Trio docs, "Designing for multiple errors"). The block of `stream` follows
the TaskGroup rules (user guide, Failures); the outputs never end as if complete after a failure

**Rejected**

- the block's error alone unchanged and the block not cancelled (Trio's "option 2"; users know the TaskGroup rules)
- one error unwrapped, several as a flat group (callers handle only the common case; flattening took a user's group
  apart)
- a library error raised `from` the group (user errors only via `__cause__`)
- only the first error (drops concurrent ones)

## Tasks of an element

Every element of a run's stage (a step occurrence, a join, a route, a gather, a loop) starts its tasks through one
function, `start_tasks` (`strom._interpreters.run_context`, 2026-11-11): a task group of their own, the stage note on
their errors, the end of their output stream. A step passes no name: its tasks note their errors where they set the
failure flag. Measured (`bin/ab.py`, `BENCH_SCALE=0.5`, 15 interleaved runs pinned to the P-cores, 2026-11-11): the
`run_overhead_one_item`, `product_stages` and `recording` rows within noise (p ≥ 0.065), but for one bimodal row of the
thread backend (0.56, p 0.019, an IQR as large as its median)

**Rejected**

- that frame written out per kind (five copies until 2026-11-11)
- an async context manager around a kind's own task group (a join checks that every input is complete between the end of
  its tasks and the handling of their errors: after such a block the check would neither be noted nor come before the
  end of the stream)

## Pool tasks of a failed run

Its running pool tasks finish and occupy the pool for the next run (left as is; interrupting them is an open task in
`docs/todo.md`, cooperative cancellation)

## Recorder

Events as data (a recorder's error ends the run like a user's error and never hides the run's own error):
`Recorder = Callable[[Event], None]`, `StatsRecorder` a fold, `combine_recorders` a fan-out; fixed clocks, not
parameters (2026-11-07): `time.perf_counter` on the event loop and for durations in pool workers, `time.thread_time` for
CPU time; the tests check the partition by the chain of readings (each `wait_started_at` is the previous `ended_at`) and
the folded totals with `math.isclose`, and times by lower bounds of intentional sleeps. A recorder whose `RunStarted`
returned gets exactly one `RunFinished`, one that raised none; `combine_recorders` keeps that for its children like
`ExitStack` (2026-11-06). `StatsRecorder` is single-use (a second `RunStarted` raises, failing that run at its start;
`stats()` only after `RunFinished`, 2026-11-06). The contract (no blocking, own I/O errors, events may grow) is the
`Recorder` docstring

**Rejected**

- per-run and per-step handles (safe call order, but more public names)
- clocks as run parameters `stream(..., clock=, cpu_clock=)` (2026-11-06 to 2026-11-07; only tests passed one: a clock
  that can't be pickled failed recording runs only on backends without shared memory, a decreasing one gave negative
  times unchecked, a `ManualClock` pickled to a worker stood still; Trio's `clock=` drives its scheduler, strom's only
  timestamped events)
- the event loop's `loop.time()` (a Python method: 145 vs 91 ns per reading, 2026-11-07; pool workers have no loop, so a
  virtual-time loop would mix virtual and real time in `pool_wait_time`; uvloop's is coarse [unverified])
- a private module-level clock monkeypatched by tests (a global seam, and the plumbing stays)
- clocks on the recorder (a combined recorder silently overrode its children's clocks)
- isolating recorder errors (Trio disables, OpenTelemetry swallows: incomplete metrics nobody notices)
- a `Clock` protocol with `now()` and clock classes (four public names for two functions)
- bundling recorder and clocks in a `Metrics` class (longer common case, one more public class, fixes only a clock
  passed without recorder)
- `RunFinished` after every attempted `RunStarted` (a `StatsRecorder` refusing a second run would take its `RunFinished`
  for its own run's end)
- a run id on every event so one `StatsRecorder` folds concurrent runs (a field per input event for a rare case)
- a reusable `StatsRecorder` with a reset (an overlapping run cleared the first run's totals, which then failed far from
  the cause)
- only the first error when several children raise on `RunFinished` (hides the others)

## Step ids

Position path; the order of the stage from `RunStarted.steps` (`step_ids`, a pure walk of the fused stage mirroring
`_run_streaming`; a property test checks that the events' ids equal it, 2026-11-06)

**Rejected**

- numbering in start order (followed task scheduling: branch steps came after later steps)
- a pre-order number (needs subtree sizes, loses the branch)
- a path over the binary chain (`(a|b)|c` ≠ `a|(b|c)`)
- numbering a rebuilt stage (one step object can sit in two places)
- `order=True` (left before right only alphabetically)
- `Side` as an enum (extra public class)
- the names `Branch`/`Side` for the enclosing stage and the part (the body of a gather or loop is no branch:
  `Enclosing`/`Part`, 2026-11-06)
- a position-only `StepId` (public API change for no defect; `name` and `concurrency` describe the position)
- caching its hash (recording: within noise)
- an explicit pre-order sort key `preorder` (redundant once `RunStarted.steps` carries the order, 2026-11-06)
- collecting the ids while starting (joins, routes, gathers and loops start their parts lazily: a barrier in every
  combinator)

## Event classes

Plain `@final` classes with `__slots__`, `__match_args__` and `Final` attributes; `RunStarted` (with the step
occurrences), one `InputHandled` per input a task took, whatever its `Outcome` (done, failed, cancelled), with its wait
and all counts; one `TaskFinished` per task whose coroutine ran (hence not `StepFinished`); `PoolTaskFinished`;
`RunFinished` with the run's `Outcome`. Both carry the task index `task`: per task, the events partition its lifetime
(each `wait_started_at` is the previous `ended_at`: one clock read per input and step less). Intervals end in
`ended_at`, closing events are `<Subject>Finished`; field names follow the naming conventions (`ARCHITECTURE.md`)
(2026-11-06)

**Rejected**

- `StepStarted` per step occurrence (static facts: `RunStarted.steps`)
- `Processed` and `Failed` (one fact in two events; a failed or cancelled input's outputs and time were lost)
- `failed: bool` (drops cancelled inputs, and a run's end needs another flag)
- `error: Exception | None` (keeps tracebacks alive in buffering exporters; may come later as a last field)
- durations instead of timestamps (spans need points in time)
- the partition per step occurrence only, without `task` (nobody could check it nor nest spans per task)
- recording a skipped pool task's input at once (a second cancelled path, idle time that was no wait)
- keyword-only constructors (not measured yet)

## Law rewrites

Only call-preserving ones: `first(f) | first(g) -> first(f | g)`, `product(f, identity()) -> first(f)` (same calls on
both interpreters, 2026-11-01)

**Rejected**

- interchange and copy (common subexpressions): they change calls (see Semantics)
- allowing them for pure stages needs an effect marker (public API)

## Sum types

`route` (ArrowChoice `+++`) as its own kind `Route`: `choose`/`from_left`/`from_right` composed by lifting (dist/undist
inside the node), branches lifted to carry the passed-through element, nothing kept or counted at the route; tags
`Left`/`Right`: `@final` frozen dataclasses with an explicit covariant TypeVar (pyright infers PEP 695 ones invariant);
routing by `match` on the tags (`isinstance` on the library's own sum type is accepted); `left`/`right` = `route` with
`identity()`; `tag_by(pred)`; no operator

**Rejected**

- tagged tuples `tuple[Literal["left"], A] | …` (a tagged value is also a pair: `first` treats the tag as data)
- an untagged union with a `TypeIs` predicate (mypy and ty inferred `Right[int | str]`, pyright needed a cast)
- a 1:1 `tagging(fn)` factory (factories are 1:0..n)
- an operator (`^` takes no keyword arguments: two spellings; `+` would mean `<+>`, `&` suggests the rejected `&&&`)
- a generalised `Join` (counting per branch step, pending state)
- dist/undist as steps (change step ids; must be 1:1 inside branches)
- `<+>` deferred (close to the rejected `fanout`)

## Fusion

An optimisation pass (`fused`) before streaming runs, no new representation: consecutive event-loop steps become one
ordinary `Step` with an `AsyncExpand` leaf (the interpreters do not know about fusion); one loop over
`Stage[Never, object]` elements, so rebuilding takes the library's casts besides the iterator registry's one (checked by
the tests that fusion keeps the meaning); event-loop steps have no `buffer_size`: their queue holds twice the consumer's
concurrency, never less than the default `buffer_size`. Sandbox, 3 interleaved runs, ratio of µs per item: 1 / 3 / 6
event-loop steps 0.56 / 0.41 / 0.34, recorded 6 steps 0.21, `first(stage)` 0.67, fan-out 0.51; source alone, joins and
pool steps within noise

**Rejected**

- `buffer_size=0` as fusion switch (rendezvous is slower; ambiguous concurrency; mixes capacity and execution strategy)
- a fused leaf kind with member names, member positions and per-member error notes (fusion leaked into the
  representation and the interpreter)
- queue = 2 x consumer concurrency (a queue of 2 for single consumers: source alone 1.19 -> 3.60,
  `product(stage, stage)` 10.96 -> 19.37 µs per item)
- pulled steps (`_Pulled`: a second step engine, stretched `Receiver` meaning, broken `concurrency` meaning, joins
  1.06-1.14x slower)
- fusion inside the interpreter (not inspectable; one count per member in branches)
- a group stage kind (an arm in every dispatcher)
- units separate from stages (a shared loop slowed joins by about 1.6x)
- fusing into steps that wait (suffix: per-output cost for every step; prefix: serialises fan-out unless concurrency 1)
- a `_Group` record next to the single step (two representations of one value)
- a right-to-left fold with the fused form as data (`_Grouped`/`_GroupedThen`/`_Unfused`: 29 definitions) or as
  parameters of a typed recursion (22): no casts, but more and harder code than the loop (14)
- a typed zipper object (more variants)
- always fusing single steps (a generator per input)
- a synchronous group leaf (`Expand`: a group dropping many items would block the event loop)

## Gather, loop

Own kinds like `Join` (body plus `Focus`), shared `_InFlight`; `concurrency` = inputs in flight; part `body`. A gather
in a branch is counted although always 1:1 (+1/-1 cancel: equivalent mutant), for uniformity

**Rejected**

- on top of `route` (no cycle)
- bounded feedback with Parks-style deadlock detection
- FIFO feedback (model: peak 190 vs 14 items)
- no admission limit (unbounded queues)
- `buffer_size` as the limit (mixes capacity and in-flight inputs)
- part `left`

## Loop name

The feedback combinator is `loop` (the user's choice, 2026-11-04; the term throughout: `Loop`, `_*_loop`, default name
`loop(f)`); its docstring leads with the convention (`Left`: continue, `Right`: output) and a paging example; the
factory table's unprefixed row is labelled `(none)`, not `loop`

**Rejected**

- `iterate` (Haskell's `iterate` builds an infinite sequence `x, f x, f (f x), …`; Python readers take it for iterating
  over items)
- `repeat_until`
- `feedback`

## Product name

The monoidal product (`***`) is `product` (the user's choice, 2026-11-04; the term throughout, also in tests and
benchmark ids; its internal kind stays `Join`); its docstring shows `duplicate() | product(f, g)` for one item into two
stages and the Cartesian product of 1:0..n branches

**Rejected**

- `parallel` (every stage already runs concurrently: the name hid that the input must be a pair and that outputs
  multiply)
- `both`
- `on_pair`
- `bimap` (exact only for 1:1 branches)

## Filter name

The predicate filter is `where` (the user's choice, 2026-11-04; also in tests and benchmark ids)

**Rejected**

- `filter_` (the trailing underscore that avoids shadowing the builtin `filter` reads as a typo)
- `keep`

## Overlap in tests

Barriers, events, `Tracker.saturating`

**Rejected**

- sleeps (slow, timing-dependent)
- virtual-time loops (can't cover thread sleeps) [unverified]
- a manual clock in real runs (non-deterministic interleavings)

## Static typing tests

mypy; one table `STATIC_CHECKS` (`reveals` / `rejects` / `accepts`)

**Rejected**

- ty (see `docs/todo.md`)

## pyright strict

The library in strict mode as a `src` execution environment listing the rules (`strict = ["src"]` can't be overridden
per rule); dispatchers on the open `Stage` class end in `case _:`, matches on closed unions (`Leaf`) name every kind
instead, so that the rule checks them; `reportPrivateUsage`, `reportUnusedClass`, `reportUnusedFunction` on since
2026-11-05 (see Module structure). Left out (65 errors on 2026-11-02, 55 of them these):
`reportUnknownArgumentType`/`MemberType`/`VariableType` (pyright's own Unknowns: the type parameters a stage kind adds
to `Stage[I, O]` after `match`, `isinstance` on `ExceptionGroup`; mypy's `disallow_any_expr` guards against `Any`),
`reportUnnecessaryComparison` (flags the `case unknown: assert_never(unknown)` arms that keep untagged items from
untyped code from vanishing)

**Rejected**

- strict for the tests (untyped pytest and hypothesis API)
- casts or methods per stage kind to bind the extra type parameters for the dispatchers (casts; OO dispatch is rejected
  under Architecture; `Focused.with_focus` rebuilds a kind and dispatches nothing, see Lifting)
- a typed local for the group (pyright narrows it to the assigned `BaseExceptionGroup[Unknown]`)

## Checker false positives

A false positive of one checker gets that checker's ignore comment on its line, with a dated entry in
`.claude/rules/typing.md`, and the code keeps the shape the other two accept (2026-11-11). Each checker has a comment of
its own and fails on one it no longer needs, so an ignore expires with its bug: `# type: ignore[code]` is mypy's alone
(pyright's `enableTypeIgnoreComments` is off), `# pyright: ignore[rule]` is checked by
`reportUnnecessaryTypeIgnoreComment`, `# ty: ignore[rule]` by `unused-ignore-comment` as an error

**Rejected**

- shaping the code so that the checker passes (2026-11-06 to 2026-11-11: the next item of an `io_stage` iterator as a
  bound method of its key with a dummy argument, and explicit type arguments in `_make_step`): a shape stays when the
  bug is fixed; `_make_step` no longer needed its type arguments, and nothing said so
- one `# type: ignore` for mypy and pyright together (an ignore for the false positive of one blinds the other on that
  line, and pyright reports the one mypy alone needs as unnecessary)
- ty's default, a warning for an unused ignore (`ty check` passes with it)

## Module structure

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

## Markdown formatter

mdformat with mdformat-gfm and mdformat-frontmatter (2026-11-10), as a pre-commit hook in pre-commit's own venv (pure
Python, runs on NixOS; no `uv.lock` change, which would make every example's lock stale); `.mdformat.toml`: `wrap = 120`
(paragraphs filled to ruff's line-length, so wrapping is uniform and automatic), consecutive numbering, compact tables.
It checks that the rendered HTML is unchanged and escapes `<` and `[` where they could start markup. Not wrapped: table
rows (GFM rows are one line), code blocks, front matter, long link targets. So tables hold only short cells, every line
stays within 120 characters (`bin/check_docs.py`, in `make lint`; front matter, lines with a URL and, until
restructured, the tables of `docs/research/` exempt), and this file has a section per topic instead of a table row

**Rejected**

- this file as a table (rows of up to 6,500 characters: unreadable unwrapped, and every edit a diff of the whole row)
- HTML tables (mdformat leaves them alone, but the source is hard to read and edit)
- `<br>` in table cells (still one line)
- Prettier (Node, not in the dev shell; mdformat's docs list AST-changing bugs)
- rumdl and dprint (native PyPI binaries need nix-ld, like ruff)
- padded tables (the long rows of `docs/decisions.md` and `ARCHITECTURE.md` became thousands of columns wide)
- `wrap = "keep"` (hand wrapping, nothing keeps lines under 120 or uniform)

## Tool sources

ruff, pyright and ty only from nixpkgs (dev shell, jail, hooks; tox runs the make targets, see Checks), pinned by
`flake.lock`; Python tools from `uv.lock` (the Makefile runs them with `uv run --frozen`)

**Rejected**

- mypy from nixpkgs (the static typing tests run `sys.executable -m mypy` and skip without it, also in the tox test
  envs)
- both sources (nixpkgs ruff 0.17.2 vs. locked 0.17.3, 2026-11-03)
- only PyPI (the ruff and ty wheels need nix-ld, the pyright wrapper downloads a node that needs it too: none runs in
  the jail)

## Async tests

pytest-asyncio (rules: `.claude/rules/tests.md`); the Hypothesis tests stay sync, although pytest-asyncio also runs
`@given` on `async def` tests (tried with `-n 4` and the `ci` profile)

**Rejected**

- a hook in `conftest.py` running coroutine tests (pytest-asyncio covers async fixtures too)
- every test async (async helpers for no gain)

## Test settings

`make test`/`cov` and tox run pytest with `-n auto` (suite 48 -> 10–22 s, 20 cores, 2026-11-03); Hypothesis profiles
`dev` (default) and `ci` in `tests/conftest.py`, chosen with the plugin's `--hypothesis-profile` (suite 47 / 187 s at 60
/ 300 examples, 2026-11-03); the static typing tests keep mypy's cache in `.mypy_cache`, one per configuration,
interpreter and xdist worker (both tests 3.6 -> 0.44 s warm)

**Rejected**

- `-n auto` in `addopts` (pytest-xdist disables the benchmarks with only a warning; one test 1.8 -> 2.8 s)
- `--dist worksteal` (no gain)
- an environment variable for the profile (the plugin's option exists; the test module's own profile had silently
  overridden it)
- one cache for both configurations (they invalidate each other's entries)
- one cache for all processes (contention for mypy's SQLite cache, 5 s lock timeout)
- temporary caches (cold every run)

## Benchmarks

Full pytest-benchmark port; cost per step derived from two rows (see `benchmarks/benchmark.py`); the rounds of a
benchmark run on one `asyncio.Runner` with its pools opened on it (2026-11-05: no round starts a loop). A revision that
a recorded measurement is against is a tag `baseline/<date>` (2026-11-11; the list: `.claude/rules/tests.md`), so that
`bin/ab.py` can still run against it after the history was rewritten. The first one is `baseline/2026-11-11`; the
measurements before it name their state in words and by date

**Rejected**

- hybrid port
- extending the hand-rolled printer with median/IQR/JSON
- a per-step metric t_n / n (charged the source and the run to the steps: +54% for 1 step)
- citing a baseline by its commit hash (the history was squashed on 2026-11-10: the three commits the docs cited hung on
  the reflog only, which `git gc` prunes and no clone has)
- tags on those three commits (set and removed on 2026-11-11, the user's decision: they kept the squashed history, and
  `bin/ab.py` runs today's benchmarks on both sides, which import names those states lack)
- the date of a measurement in place of its revision, where the revision can be kept (a plan's step "reproduce" needs
  the code)

## Test layout

One test module per library module (the layout: the docstring of `tests/conftest.py`); test data in the test modules
that need it (the static checks define their types in `STATIC_SETUP`); directories without `__init__.py` (test module
names must be unique); the GIL warning filter in `filterwarnings`

**Rejected**

- one module per part of the former nine-part `test_pipelines.py` (parts cut across library modules)
- test packages with `__init__.py` (module names `tests.…`, no gain)
- `from helpers import TRACK` (the autouse fixture replaces it: a stale tracker)
- `pytestmark` per module (repeated in nearly every one)

## Test refactoring

Only selected items done; analysed and left open: a `tracker` fixture replacing the global `TRACK` and `tracked_a/b/c`,
a shared "fail on two" helper

**Rejected** (on purpose not done)

- a step-counts helper
- strategy building blocks
- `diagonal(n)`
- an "internals" heading

## Examples

Reference code for users, kept correct and apart from the tests: each `examples/*.py` checks its own results and exits 0
or 1, reporting each wrong result on stderr; `bin/run_examples.py` runs them one at a time in their own process groups,
with a timeout per example, from `make check` and tox; the tests cover the library on their own (removing the example
tests lost only `default_cpu_workers`/`default_io_workers`, now tested; functions of a `__main__` script on the process
backend: `test_process_backend_runs_functions_of_the_main_script`). Each example is a uv script (2026-11-08): a PEP 723
header with its dependencies (strom as an editable path source) and a lock of its own (`<name>.py.lock`), run with
`uv run --script --locked` and type-checked against its own environment (`--type`, part of `make type`), so the dev
environment carries no example's dependencies and examples may pin different versions of one package

**Rejected**

- example dependencies in the dev group (one version per package for all examples, and the dev environment grows with
  every example)
- a uv workspace member per example (a `pyproject.toml` and directory for each one-file script)
- `ignore_missing_imports` for example dependencies (their API unchecked)
- a copy of the example's pipelines in `tests/` (`pipelines_under_test.py`: nothing kept it in step with the example,
  and the tests named after the example checked the copy)
- tests importing the examples (tests depend on reference code)
- `tests/test_examples.py`, also behind a deselected marker (reference code in the suite; nothing runs it by default)
- running them in-process (`__main__` would be pytest: the process backend could not import their functions)
- a plain make loop (no timeout, no killing the pool workers)

## Change checks

Scripts in `bin/` for the mechanical parts of the Process (A/B benchmarks, typing and test-ID snapshots, injected bugs
in a temporary copy, run detached with a timeout), the steps as the project skill `validate-change`; typing and test-ID
diffs against a revision (`--against REV`, checked in a temporary copy) besides saved snapshots; the hook `ruff_hook.py`
leaves the rules a half-done edit breaks (F401, F811, F821, F822, F841; 2026-11-06: F821 alone blocked 186 times in four
sessions) to the end of the turn, when it checks every changed Python file (also those changed by commands) with all
rules, and leaves a file outside the repository as it is (2026-11-11); `:index` as a revision (the staged state) instead
of a snapshot commit (the jail has no git identity)

**Rejected**

- the library's rules for every Python file a session edits (probe scripts in the scratchpad, which the skill `plan`
  asks for, were reformatted and blocked: S101, E501)
- a baseline that must be saved before the first edit as the only way (the step most easily forgotten)
- a mutation-testing tool such as mutmut (generated mutants instead of the bug a test targets)
- pyperf for A/B (a second benchmark harness next to pytest-benchmark)
- make targets (arguments are awkward to pass)
- injecting into `src/` itself (a hang or an interrupted run leaves the bug in the working tree; the Hypothesis database
  and caches would record mutant runs)
- fixing F401 in the hook (it deletes an import added before its use)

## Law tests

One test per law: the `*_law_sides` functions return the sides by law name, the tests are parametrised by those names
(taken from the dict, so each law is named once); per-example `Pools`; `make test` 10.7 -> 4.8–7.7 s (20 cores,
2026-11-04) for about 35% more CPU (run-law tests serial 17–29 -> 29–37 s)

**Rejected**

- one test per family looping over its laws (its 10.2 s test bounded the suite's wall time; a failure did not name the
  law)
- a module-scoped `Pools` for all examples (27–33 s, one run 103 s; see Pool tasks of a failed run)

## Stage repr

`<Stage 'name' (step: settings; ...)>`: the name and the settings that differ from the defaults (placement,
`concurrency`, `buffer_size`) of each step occurrence and combinator, in order (`display.settings`); Hypothesis prints
failing stages with it

**Rejected**

- the generated dataclass repr (internal kinds, focuses, function addresses: 573 characters for three steps)
- the name only (a failing generated stage would not show its placement and concurrency)
- a repr rebuilt from the structure (ignores names users give)

## Internals docs

`ARCHITECTURE.md` at the root: overview, repository, packages, design notes and conventions (code, tests, naming), the
one starting point for contributors and agents; `help(strom)` is the user guide only

**Rejected**

- the "Internals" part in the package docstring (users saw naming conventions; it went stale with the module split)
- `docs/internals.md` beside design notes and code conventions in `CLAUDE.md` (two places, the conventions hidden from
  human contributors)

## User guide structure

Three parts in the package docstring (2026-11-04): 1. Quick start (example, types, running, the factory table, writing
functions, `concurrency`, handling failures), 2. Combinators by task (pairs, branching, collecting per input,
repeating), 3. Reference (semantics with the Haskell correspondences, resources vs. concurrency, metrics, fusion, order,
failures, sync code, testing, backends); section names others cite (`Backends`, `Fusion`, the factory table) kept

**Rejected**

- one flat list of sections (newcomers had to read laws and queue sizing before learning how to map a function)

## Public modules

The top level of `strom` holds what builds and runs pipelines. What only some users need is a public module beside it,
and a name is public in one place only (2026-11-11): `strom.metrics` (the recorder, the events, the statistics), like
`strom.testing` and `strom.backends`. Each has its guide in its own docstring, and the user guide a short section that
points there

**Rejected**

- the metrics names at the top level (until 2026-11-11: 17 of the 55 names of `__all__`, which only users of `recorder`
  need)
- `StatsRecorder` and `diagnose` at the top level as well (two import paths for them, or a metrics module without its
  two entry points)

## Checks

One definition of each check, a make target (2026-11-11); `make check` is lint, type, test and examples. tox runs the
targets (the envs of a Python version, and the benchmarks' results, on their own interpreter against the installed
package), and so do the git hooks: at a commit `make lint` and `make type`, beside the fixers of the changed files; at a
push `make check`, so the tests run without anyone asking (`pre-commit install` sets up both hooks; direnv does it)

**Rejected**

- the commands spelled out again per tool, in `tox.toml` and as hooks (until 2026-11-11: they drifted, as
  `bin/check_docs.py` ran in `make lint` only, and none of them ran the tests by itself)
- checks in `flake.nix` as one more, hermetic gate (`nix flake check` with the venv from `uv.lock` via uv2nix,
  2026-11-04 to 2026-11-10): a fourth definition, which the jail could not run (no `nix`), and whose sandbox has neither
  uv nor network, so that the examples, uv scripts with locks of their own, ran with the interpreter's packages only (a
  mode `--direct` of `bin/run_examples.py`), skipping those with further dependencies
- for such checks in nix: Python packages from nixpkgs (a second source of versions, see Tool sources)
- for such checks in nix: `uv sync` in the check (no network in the sandbox)

## Docs check

`bin/check_docs.py` (in `make lint`) accepts a cited path or library name only if it is tracked (2026-11-11): a clone
has only what is tracked, so a doc that cites a new file fails until the file is added (`git add`: the check says so)

**Rejected**

- accepting what merely exists in the working tree (until 2026-11-11: `docs/research/` was untracked and cited, and a
  fresh clone failed `make lint` with four missing references)
- `git add -N` for a new file (with an intent-to-add entry `git stash create`, the baseline of `bin/ab.py`, fails, and
  the revision `:index` gets an empty file)
- the stricter check only in the commit hook (a second definition of lint, see Checks)

## Agent docs

`CLAUDE.md` holds what every session needs (agreements, commands) and sends agents to `ARCHITECTURE.md` before code
work; notes on one area in `.claude/rules/*.md` with `paths` (Claude Code loads them when it reads or edits a matching
file); open tasks in `docs/todo.md`, plans in progress in `docs/plans/`; procedures as skills; usage of a script only in
its docstring; research in `docs/research/` is a snapshot of its date and is not continued (2026-11-11): what was
decided from it is recorded here, what is open in `docs/todo.md`

**Rejected**

- `AGENTS.md` (Claude Code does not load it)
- everything in `CLAUDE.md` (13.5 KB in every session, mostly unused by tooling and naming sessions)
- importing parts with `@` (imports load at start, saving no context)
- copies of script usage or skill steps in `CLAUDE.md` (they drifted)
- research notes that follow the work (`docs/research/backends.md` and `dependency_injection.md` marked their steps as
  implemented or open, 2026-11-09 to 2026-11-11: the open ones were in neither `docs/todo.md` nor a plan)

## Self-improvement

From a retrospective of 24 sessions (2026-11-06): one hook dispatcher (`.claude/hooks/dispatch.py`) registered for every
event, so that hooks change without touching `.claude/settings.json` (Claude can't write it); the rules a Bash command
touches are loaded by a hook (half the reads were `cat`/`sed`, which Claude Code doesn't count; the user asked "are the
rules respected?" four times); friction logged per session in `.checks/friction.jsonl`, with the SessionStart hook
suggesting the skill `retro` past thresholds; agreements in `CLAUDE.md` to record gotchas and corrections as they occur;
the recurring requests as skills (`review`, `plan`); `bin/check_docs.py` in `make lint` (stale references were found by
hand in four sessions); the pyright LSP plugin off for this project (163 diagnostics attached, often stale, its
navigation never used). Retrospective of 8 sessions (2026-11-08): the skill `plan` keeps the user's requirements at the
top of a plan, checks runtime claims with a probe and ends writing and revising with a review pass (the user corrected
dropped requirements twice in one session and asked for another pass on the same plan four times); the jail has only
`python3.14t` of the free-threaded build on PATH (it reverses the package order, so `uv -p 3.14` picked 3.14t)

**Rejected**

- setting `UV_PYTHON` in the jail alone (covers uv's default, not `-p 3.14` or other tools that search PATH)
- reversing `pythonVersions` for the jail (relies on how jail.nix orders PATH)
- only instructions in `CLAUDE.md` (already ignored: rules not loaded, scripts instead of Edit)
- a retrospective after every session (cost without friction)
- a scheduled cloud agent (can't read the local transcripts)
- mutmut-style generated checks for docs (the references are explicit, a plain existence check suffices)

## Test tools for users

`strom.testing` (2026-11-05): `evaluate`/`evaluate_async` (the reference semantics, public), `bag` (outputs as a
multiset by `repr`: unhashable items work, a failing assert shows the difference), `check_against_reference`
(2026-11-06; raises `AssertionError` naming the missing and extra items, like the backend checks);
`strom.testing.__all__` lists exactly these and the backend checks (pydoc and star imports showed its imports);
`RunFailed`, the `ExceptionGroup` subclass a failed run raises (`derive` keeps it through `except*`; a plain
`BaseExceptionGroup` only if an error is no `Exception`); `RunStats.step(name)` (raises on a name of several
occurrences); plumbing stages `swap`, `fst`, `snd`, `untag` (event-loop, 1:1). `bag` and `check_against_reference`
compare each item as a whole: the list of a `gather`, which comes in no particular order, is sorted by a stage after the
gather, as the docstrings of `gather`, `bag` and `check_against_reference` say (2026-11-11: the check failed on a
correct `gather` with a concurrent body)

**Rejected**

- a pytest plugin or fixtures (a dependency)
- a `key` parameter for `bag` and `check_against_reference`, to compare such lists (a public addition for what a stage
  in the pipeline under test does)
- a lambda as the sorting stage in the docs (pyright does not infer its parameter: a named function)
- `same_bag(a, b) -> bool` and `agrees_with_reference -> bool` (no difference shown)
- the message string as the only mark of a run's group (the tests imported the private constant)
- `ManualClock` (2026-11-07: the run's clocks are fixed, see Recorder)

## Resources

Two, `"cpu" | "io"`, and the resource decides both where a function runs and how its items come: "io" streams them, one
pool task each, from an iterator kept in its worker (a list or a tuple comes whole, see `io_stage` items); "cpu"
collects them in one pool task (`item_fn_of` matches the resource exhaustively, 2026-11-06); `PoolConfig` and
`RunBackends` hold one field per resource, so there is no "else" that a third one would fall into

**Rejected**

- separating placement from delivery by a parameter (a streamed cpu step: no use seen; a collected io step is what a
  returned list asks for, without a parameter on every factory)
- named resources (they would touch the factories and the stage data; open in `docs/todo.md` as cross-stage limits)

## Stage kinds

The dispatchers on `Stage` end in `case _:` (see pyright strict), so a missing arm is a runtime error, not a type error;
`test_every_stage_kind_goes_through_every_dispatcher` (`tests/stages/test_model.py`) runs a sample of every kind through
all of them (reference, run with fusion, lifted onto either element, in a `product` branch, repr) and fails when a kind
has no sample (2026-11-06; a kind is a concrete subclass of `Stage`: `Focused` is the abstract base of four)

**Rejected**

- a closed union of the kinds for dispatch (the type parameters a kind adds would be lost, see pyright strict)
- a sealed `Stage` (user subclasses would be rejected by `__init_subclass__`: a runtime check, not requested)

## Worker handles

Setup and teardown per process for blocking functions (2026-11-08): `worker_handle(open, pools)` is an `async with`
block giving a `WorkerHandle`, and `using(handle, fn)` an ordinary function of one input, so no leaf, interpreter or
pass knows handles. It means a handle per input (`with open() as h: fn(h, item)`), which is what the reference semantics
runs; the built-in backends share one per process instead, opened by its first use there and closed after the uses in
flight at the block's end. The rules a user sees: user guide, Worker handles and Failures; how it works:
`strom._runtime.worker_handles.worker_handle` and `ARCHITECTURE.md`, Concurrency and pools. Decided with it:

- on `Processes` the close is a call pinned to every worker process (2026-11-11, see Worker pool); a worker that is gone
  counts as closed;
- the lifecycle of a key is explicit states, changed in one place (`strom._runtime.worker_handles.handle_table`);
- `WorkerHandle`, `worker_handle` and `using` live in `_runtime` (they need `Pools`; `_stages` imports nothing of
  `_runtime`), `Using` itself as data in `_stages.model`.

Sources: Pekko `mapWithResource`, Beam `DoFn` setup/teardown and `Shared`, Dask worker plugins, Ray actors, SQLAlchemy
pooling guidance (one engine per process).

**Rejected**

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
