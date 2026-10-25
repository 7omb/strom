# Glossary – strom

Terms of `src/strom`, `tests/` and `benchmarks/benchmark.py`. One term per concept; definitions only.

## Terms

**Data flow**

- **item**: one element of a stream. Seen from a step it is an *input* or an *output*.
- **stage**: maps each input to a bag of outputs (1:0..n), as pure data (type `Stage`), built by the factories and `|`,
  executed by interpreters. The factory `stage()` builds one on the event loop.
- **inputs**: the iterable or async iterable a run takes its items from (the `inputs` of `stream`); the caller's, never
  closed by the run. **feeder** (`_feed`): the code putting them into the queue of the stage's first step.
- **outputs**: the async iterator of a run's outputs (`_Outputs`), valid inside the `async with` block of `stream`.
- **effect**: what a function does besides returning outputs (writing a file, sending a request); a stage for an effect
  only returns nothing.
- **pipeline**: in prose, a stage composed of others; not a type.
- **bag**: outputs compared without order; runs promise a bag, not an order.
- **product semantics**: `first`/`second` pair each output with the passed-through element; `product` pairs each output
  of one branch with each output of the other for the same input.
- **sum semantics**: `route` sends each input to one branch by its tag; each output keeps the tag.
- **tag**: `Left` or `Right`, a value of the sum type `Left[A] | Right[C]` that a route takes and emits (`left`/`right`
  are combinators, `Left`/`Right` tags). `tag_by` tags items by a predicate.
- **gather**: emits, per input, the list of a stage's outputs on it (`gather`).
- **loop**: applies a stage to each input and again to each `Left` it emits (**feedback**), emitting each `Right`
  (`loop`). Not the *event loop*.
- **factory**: a public function building a stage from a user function (`stage`, `io_stage`, `where`, `tag_by`, …) or
  from none (the **plumbing** stages `identity`, `duplicate`, `swap`, …), in `strom._stages.factories`. **combinator**:
  a public function building a stage from stages (`product`, `first`, …), in `strom._stages.combinators`.

**Stage structure**

- **step** (`Step`): one processing step, the unit that runs. Holds a leaf, `concurrency` and `buffer_size`. A **focused
  step** (`FocusedStep`) is a step applied through a focus; it runs as one step with the step's settings.
- **chain** (`Chain`): `head | tail`.
- **branch**: the `left` or `right` stage of a join or a route.
- **join** (`Join`, built by `product`): two branches applied to the pair of branch inputs through a focus: its `split`
  gives the pair and a **kept** value, `merge` combines a pair of branch results with it, `finish` receives it when the
  input is complete. A **sequence number** identifies an input in both branches.
- **route** (`Route`, built by `route`, `left`, `right`): two branches; `choose` gives each input's branch input with
  its tag, `from_left`/`from_right` make an output of each branch output. Lifting composes these functions and lifts
  both branches.
- **body**: the stage inside a gather (`Gather`) or a loop (`Loop`); its step ids show `body` where a branch's show
  `left` or `right`.
- **count**: the number of an input's items inside one branch of a join or the body of a gather or loop; the branch is
  **done** with the input at 0, the input **complete** when every branch (or the body) is done.
- **in flight** (`_InFlight`): an input a gather or loop has taken and not yet released.
- **step occurrence**: one place of a step in a stage; the same step object can occur several times. `concurrency`,
  metrics and step ids are per occurrence.
- **element**: what a chain counts, a step occurrence or a join, route, gather or loop; in a run each starts its tasks
  in a task group of its own (`start_tasks`).
- **leaf** (`Leaf`): the user's function `fn` (1:0..n) as data, with the `resource` it runs on (`None`: event loop); for
  a group, the function fusion composed from its members.
- **event-loop step**: a step whose leaf runs on the event loop without `async` (`Expand` with resource `None`); it
  never waits while handling an input.
- **fusion** (`fused`): the optimisation pass of streaming runs that turns consecutive event-loop steps into a
  **group**: one ordinary step named by their chain; its steps are its **members**. **SKIP** (`_Skip`, private to
  fusion): marks a member's input without outputs; never an output.
- **ItemFn** (`ItemFn[I, O]`): maps one input to an async generator of its outputs; built from a leaf per run.
- **focus** (`Focus`): how a focused step applies its leaf to an input: `split` gives the leaf's input and a kept value,
  `merge` combines each output with it, `finish` receives it when the input is handled. The kinds that hold a focus (a
  focused step, a join, a gather, a loop) are the **focused** stages (`Focused`).
- **lift**: apply a stage to one element of a pair (`first`, `second`); the other element is **passed through**. A
  focused stage is lifted by wrapping its focus (`with_focus`), a chain and a route by lifting their parts.

**Execution**

- **run**: one execution of a stage on the items of its inputs, by the **runner** `stream` with a `Pools`, for the
  duration of its `async with` block (the run's **scope**, like a TaskGroup's). The iterators a run opens in pool
  workers belong to its scope (`RunScope`, a token per run); **releasing** the scope at the run's end
  (`StreamingBackend.release`, `release_scope`) closes those left there.
- **interpreter**: a function executing a stage: `start_streaming` (one bounded queue per step) and `run_reference`
  (sequential).
- **reference semantics** (`run_reference`, public as `strom.testing.evaluate`; `helpers.meaning` in the tests): a stage
  as a plain function `input -> list of outputs`, which runs must agree with (as a bag).
- **run context** (`RunContext`): what the parts of a streaming run share; its mutable part is the **run state**
  (`RunState`: failure flag and run errors).
- **offloader** (`Offloader`): how one step occurrence of a streaming run runs blocking functions: `listed`
  (`cpu_stage`) or `streamed` (`io_stage`).
- **resource**: `"cpu"` or `"io"`; it decides both where a function runs and how its items come (collected in one pool
  task, or streamed: an iterator one item per pool task, a list or a tuple whole).
- **pool**: the role: what blocking functions of one resource run on, one per resource and `Pools` (the io pool, the cpu
  pool). **backend** (`Backend`): what runs a pool, behind the interface for implementers (`strom.backends`); created on
  first use by a **backend config**, a callable such as `Threads(...)`, `Processes(...)`, `FromExecutor(...)`
  (`PoolConfig` holds one per resource). A **streaming backend** (`StreamingBackend`) honours affinity, as the io pool
  needs. **executor** only names the `concurrent.futures` object behind `FromExecutor`; a **broken** one
  (`BrokenExecutor`) is dropped and replaced.
- **Pools**: the object holding one pool per resource, for one or more runs.
- **pool task**: one call submitted to a pool. **pool worker**: a thread, process or remote worker of a pool. **pool
  thread**: a pool worker that is a thread; used where only threads apply.
- **pinning pool** (`PinningPool`): the threads behind the built-in thread and process backends: a call runs on any of
  them or on the one it is **pinned** to, behind what that one runs. A **cleanup** is a call pinned to every thread and
  never cancelled (the release of a scope, the close of a worker handle). A thread's **worker** (`Worker`) is what it
  runs its calls with: itself, or a child process it forwards them to.
- **offload**: run a blocking function as a pool task.
- **pool-worker-side helpers**: functions that run in a pool worker around the user's function.
- **worker id** (`WorkerId`): a pool worker, the target of affinity; it holds iterators in its **registry**
  (`_Registry`, `strom._runtime.iterator_registry`). **iterator key** (`IteratorKey`): an `io_stage` iterator in a
  registry. **affinity**: the worker a pool task must run on.
- **shared memory**: pool workers are threads of this interpreter (the thread backend); without it, functions, items and
  results are pickled.
- **opener**: a context manager factory (`Callable[[], AbstractContextManager[R]]`) that a worker handle enters.
  **handle**: what an opener yields (an engine, a client, a model). **worker handle** (`WorkerHandle`, from
  `worker_handle`): a handle opened once per process on its first use there, by a pool worker, and closed at the end of
  its block; its **key** names it in every process. **handle table** (`HandleTable`): the worker handles of one process;
  **marked** threads (`init_handles`) use it.
- **task**: one of the `concurrency` asyncio tasks of a step; it takes one input after another and handles it.
- **handling**: what a task does with one input: turning it into its 0..n outputs and putting them downstream.
- **concurrency**: maximum inputs of one step occurrence, or of a gather or loop, in flight. **buffer_size**: capacity
  of a step's output queue, or of a join's queues.
- **consumer**: the part taking a stage's outputs: the next step, an internal loop of a join, route, gather or loop, or
  the code taking a run's outputs. **intake** (`_intake`): how many inputs a stage takes at once.
- **backpressure** / **blocked**: waiting for downstream to accept an output.
- **queue**: the bounded queue between two steps. **end of stream**: `shutdown()` of a queue.
- **CPU backend kind** (`CpuBackendKind`): the literal of `Pools.open` choosing the cpu pool's built-in backend.

**Metrics**

- **step id** (`StepId`): a step occurrence's position in the run's stage: the stages **enclosing** it (`Enclosing`: a
  join, route, gather or loop, with the **part** the step is in, `Part`: a branch, `left` or `right`, or the `body`) and
  its index in its chain.
- **event** (`Event`): read-only data about a run. **recorder** (`Recorder`): a function of an event.
- **outcome** (`Outcome`): how an input's handling (`InputHandled`) or a run (`RunFinished`) ended: done, failed, or
  cancelled (the run failed elsewhere, was left early or cancelled from outside).
- **partition**: per task, idle, busy and blocked time add up to its lifetime (its events leave no gap).
- **stats**: `StepStats` per step occurrence and `RunStats` per run (from `StatsRecorder`). **hint** (`Hint`): finding
  of `diagnose`.

**Failures**

- **failure flag** (`FailureFlag`): set when a run fails; its pool tasks that have not started are then skipped
  (`PoolTaskSkipped`): each is **guarded** by the run, so a worker sharing its memory sees the flag, another one the
  copy pickled with the task.
- **stage note**: `in stage '<name>'`, added once per stage the error passed.
- **run errors** (`run_errors`): the errors that ended a run, as raised (a user's own exception group stays whole); a
  failed run raises them in one exception group.
