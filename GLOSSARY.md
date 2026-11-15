# Glossary – strom

Terms of `src/strom`, `tests/` and `benchmarks/benchmark.py`, and of the development tools (`tools/`, Tools below). One
term per concept and per bullet, the terms of a family under their parent; definitions only: how a thing behaves is in
its docstring.

## Terms

**Data flow**

A run applies a stage to each item of its inputs, and its outputs are a bag. Factories build stages from functions,
combinators build them from stages.

- **item**: one element of a stream.
  - **input**, **output**: an item as a step takes it, or as it emits it.
- **stage** (`Stage`): a mapping of each input to a bag of outputs (1:0..n), as pure data, built by the factories and
  `|` and executed by interpreters. The factory `stage()` builds one on the event loop.
- **pipeline**: in prose, a stage composed of others; not a type.
- **inputs**: the iterable or async iterable a run takes its items from (the `inputs` of `stream`); the caller's, never
  closed by the run.
  - **feeder** (`_feed`): the code that puts the inputs into the queue of the stage's first step.
- **outputs**: the async iterator of a run's outputs (`_Outputs`), valid inside the `async with` block of `stream`.
- **bag**: outputs compared without order; a run promises a bag, not an order.
- **effect**: what a function does besides returning outputs (writing a file, sending a request); a stage for an effect
  only returns nothing.
- **factory**: a public function that builds a stage from a user function (`stage`, `io_stage`, `where`, `tag_by`, …) or
  from none, in `strom._stages.factories`.
  - **plumbing** stage: a stage of a factory that takes no function (`identity`, `duplicate`, `swap`, …).
- **combinator**: a public function that builds a stage from stages (`product`, `first`, …), in
  `strom._stages.combinators`.
- **product semantics**: what the combinators on pairs mean: `first` and `second` pair each output with the
  passed-through element, `product` pairs each output of one branch with each output of the other for the same input.
- **sum semantics**: what `route` means: each input goes to one branch by its tag, and each output keeps the tag.
- **tag**: `Left` or `Right`, a value of the sum type `Left[A] | Right[C]` that a route takes and emits (`left` and
  `right` are combinators, `Left` and `Right` tags); `tag_by` tags items by a predicate.
- **gather** (`gather`): the combinator that emits, per input, the list of a stage's outputs on it.
- **loop** (`loop`): the combinator that applies a stage to each input and again to each `Left` it emits, and emits each
  `Right`. Not the *event loop*.
  - **feedback**: the `Left` items that go into the loop's stage again.

**Stage structure**

A stage is a step, a chain, a join, a route, a gather or a loop. A step holds a leaf, the user's function as data; a
focus says how a lifted step applies its leaf.

- **step** (`Step`): one processing step, the unit that runs; it holds a leaf, `concurrency` and `buffer_size`.
  - **focused step** (`FocusedStep`): a step applied through a focus; it runs as one step with the step's settings.
  - **step occurrence**: one place of a step in a stage; the same step object can occur several times, and
    `concurrency`, metrics and step ids are per occurrence.
  - **event-loop step**: a step whose leaf runs on the event loop without `async` (`Expand` with resource `None`); it
    never waits while handling an input.
- **leaf** (`Leaf`): the user's function `fn` (1:0..n) as data, with the `resource` it runs on (`None`: event loop); for
  a group, the function fusion composed from its members.
- **ItemFn** (`ItemFn[I, O]`): a function from one input to an async generator of its outputs, built from a leaf per
  run.
- **chain** (`Chain`): `head | tail`.
- **element**: what a chain counts: a step occurrence, or a join, route, gather or loop; in a run each starts its tasks
  in a task group of its own (`start_tasks`).
- **branch**: the `left` or `right` stage of a join or a route.
- **body**: the stage inside a gather (`Gather`) or a loop (`Loop`); its step ids show `body` where a branch's show
  `left` or `right`.
- **join** (`Join`, built by `product`): two branches applied to the pair of branch inputs through a focus.
  - **sequence number**: what identifies an input in both branches of a join.
- **route** (`Route`, built by `route`, `left`, `right`): two branches of which each input takes one. `choose` gives
  each input's branch input with its tag, `from_left` and `from_right` make an output of each branch output; lifting
  composes these functions and lifts both branches.
- **focus** (`Focus`): how a focused step applies its leaf to an input: `split` gives the leaf's input and a kept value,
  `merge` combines each output with it, `finish` receives it when the input is handled. A join's focus splits an input
  into the pair of branch inputs, merges each pair of branch results and finishes when the input is complete.
  - **kept** value: what `split` sets aside of an input for `merge` and `finish`.
  - **focused** stage (`Focused`): a stage of a kind that holds a focus: a focused step, a join, a gather, a loop.
- **lift**: apply a stage to one element of a pair (`first`, `second`). A focused stage is lifted by wrapping its focus
  (`with_focus`), a chain and a route by lifting their parts.
  - **passed through**: said of the other element of the pair, which the lifted stage does not touch.
- **count**: the number of an input's items inside one branch of a join, or inside the body of a gather or loop.
  - **done**: said of a branch or a body with an input once its count is 0.
  - **complete**: said of an input once every branch, or the body, is done with it.
- **in flight** (`_InFlight`): said of an input that a gather or loop has taken and not yet released.
- **fusion** (`fused`): the optimisation pass of streaming runs that turns consecutive event-loop steps into a group.
  - **group**: the one ordinary step that fusion makes of consecutive event-loop steps, named by their chain.
  - **member**: a step of a group.
  - **SKIP** (`_Skip`, private to fusion): the mark of a member's input without outputs; never an output.

**Execution**

A run executes a stage with a `Pools`. Each step has tasks; a task takes inputs, offloads blocking functions to a pool
and puts the outputs into the step's queue.

- **run**: one execution of a stage on the items of its inputs, with a `Pools`, for the duration of the `async with`
  block of `stream`.
  - **runner**: what starts a run: `stream`.
  - **scope** (`RunScope`, a token per run): the block of a run, like a TaskGroup's; the iterators a run opens in pool
    workers belong to it.
  - **release** (`StreamingBackend.release`, `release_scope`): end a run's scope in the pool workers, which closes the
    iterators left there.
- **interpreter**: a function that executes a stage: `start_streaming` (one bounded queue per step) and `run_reference`
  (sequential).
- **reference semantics** (`run_reference`, public as `strom.testing.evaluate`; `helpers.meaning` in the tests): a stage
  as a plain function `input -> list of outputs`, which runs must agree with (as a bag).
- **run context** (`RunContext`): what the parts of a streaming run share.
  - **run state** (`RunState`): its mutable part: the failure flag and the run errors.
- **task**: one of the `concurrency` asyncio tasks of a step; it takes one input after another and handles it.
  - **handling**: what a task does with one input: turning it into its 0..n outputs and putting them downstream.
- **concurrency**: the maximum number of inputs of one step occurrence, or of a gather or loop, in flight.
- **buffer_size**: the capacity of a step's output queue, or of a join's queues.
- **queue**: the bounded queue between two steps.
  - **end of stream**: the `shutdown()` of a queue.
- **consumer**: the part that takes a stage's outputs: the next step, an internal loop of a join, route, gather or loop,
  or the code that takes a run's outputs.
  - **intake** (`_intake`): how many inputs a stage takes at once.
- **backpressure**, **blocked**: said of a wait for downstream to accept an output.
- **resource**: `"cpu"` or `"io"`; it decides both where a function runs and how its items come (collected in one pool
  task, or streamed: an iterator one item per pool task, a list or a tuple whole).
- **offload**: run a blocking function as a pool task.
  - **offloader** (`Offloader`): how one step occurrence of a streaming run offloads: `listed` (`cpu_stage`) or
    `streamed` (`io_stage`).
- **pool**: the role: what the blocking functions of one resource run on (the io pool, the cpu pool).
  - **Pools**: the object that holds one pool per resource, for one or more runs.
  - **pool task**: one call submitted to a pool.
  - **pool worker**: a thread, process or remote worker of a pool.
  - **pool thread**: a pool worker that is a thread; used where only threads apply.
  - **pool-worker-side helpers**: functions that run in a pool worker around the user's function.
- **backend** (`Backend`): what runs a pool, behind the interface for implementers (`strom.backends`).
  - **backend config**: a callable that creates a backend on first use, such as `Threads(...)`, `Processes(...)` or
    `FromExecutor(...)`; `PoolConfig` holds one per resource.
  - **streaming backend** (`StreamingBackend`): a backend that honours affinity, as the io pool needs.
  - **CPU backend kind** (`CpuBackendKind`): the literal of `Pools.open` that chooses the cpu pool's built-in backend.
  - **executor**: the `concurrent.futures` object behind `FromExecutor`, and nothing else.
  - **broken** executor: one that raised `BrokenExecutor`.
  - **shared memory**: what a backend has whose pool workers are threads of this interpreter (the thread backend);
    without it, functions, items and results are pickled.
- **worker id** (`WorkerId`): the name of a pool worker, the target of affinity.
  - **affinity**: the worker a pool task must run on.
  - **registry** (`_Registry`, `strom._runtime.iterator_registry`): what holds the open iterators of a pool worker.
  - **iterator key** (`IteratorKey`): the name of an `io_stage` iterator in a registry.
- **pinning pool** (`PinningPool`): the threads behind the built-in thread and process backends.
  - **pinned**, **unpinned**: said of a call that must run on one thread, behind what that thread runs, or that may run
    on any.
  - **discarded**: said of a result or an error that nobody waits for any more.
  - **cleanup**: a call pinned to every thread and never dropped (the release of a scope, the close of a worker handle).
  - **worker** (`Worker`) of a thread: what the thread runs its calls with: itself, or a child process it forwards them
    to.
  - **stateful**, **stateless**: said of a thread whose worker holds, or does not hold, what later pinned calls will
    need (an open iterator).
- **drop**: let go of what will not be used any more: a call still queued at the shutdown of a pinning pool (it never
  runs), a broken executor, a broken child process.
- **opener**: a context manager factory (`Callable[[], AbstractContextManager[R]]`) that a worker handle enters.
- **handle**: what an opener yields (an engine, a client, a model).
  - **worker handle** (`WorkerHandle`, from `worker_handle`): a handle opened once per process on its first use there,
    by a pool worker, and closed at the end of its block.
  - **key** of a worker handle: its name in every process.
  - **handle table** (`HandleTable`): the worker handles of one process.
  - **marked** thread (`init_handles`): a thread that uses the handle table.

**Metrics**

- **step id** (`StepId`): a step occurrence's position in the run's stage: the stages enclosing it and its index in its
  chain.
  - **enclosing** stage (`Enclosing`): a join, route, gather or loop around a step, with the part the step is in.
  - **part** (`Part`): a branch (`left` or `right`) or the `body`.
- **event** (`Event`): read-only data about a run.
- **recorder** (`Recorder`): a function of an event.
- **outcome** (`Outcome`): how an input's handling (`InputHandled`) or a run (`RunFinished`) ended: done, failed, or
  cancelled (the run failed elsewhere, was left early or cancelled from outside).
- **partition**: the property that, per task, idle, busy and blocked time add up to its lifetime (its events leave no
  gap).
- **stats**: `StepStats` per step occurrence and `RunStats` per run (from `StatsRecorder`).
- **hint** (`Hint`): a finding of `diagnose`.

**Failures**

- **failure flag** (`FailureFlag`): what is set when a run fails; its pool tasks that have not started are then skipped
  (`PoolTaskSkipped`).
  - **guarded**: said of a pool task that checks its run's failure flag before it starts; a worker sharing the run's
    memory sees the flag, another one the copy pickled with the task.
- **stage note**: `in stage '<name>'`, added to an error once per stage it passed.
- **run errors** (`run_errors`): the errors that ended a run, as raised (a user's own exception group stays whole); a
  failed run raises them in one exception group.

## Tools

Terms of `strom_tools`. Where a term of the library recurs, it has the word in front that tells it apart: a hook event
is no metrics event, a friction event neither, an example's outcome no outcome of a run.

**Workspace**

- **repository** (`Repository`): a checkout of this project, the value every tool function takes.
  - **state directory** (`.checks/`): where the tools keep their snapshots, the friction log and the memos, unversioned.
- **process run** (`ProcessRun`): the outcome of a command a tool started: its exit code (none after a timeout), stdout
  and stderr.
- **revision** (`Revision`): what a change is compared with: a commit, the working tree (`.`) or the index (`:index`).
  - **copy** of a revision: its files exported into a directory of its own (`checkout`, `library_copy`).

**Change checks**

- **snapshot**: lines saved in the state directory to compare a later state with.
  - **line diff** (`LineDiff`): the lines removed and added between two snapshots, compared as multisets.
- **diagnostic**: a line of a type checker (`Checker`), without its line and column.
- **mutant**: a copy of the code with an injected bug.
  - **bug** (`Bug`): what a mutant injects: a replacement or a patch.
  - **trial** (`Trial`): a run of the tests on the copy without the bug, then with it.
  - **verdict** (`Verdict`): what a trial gives: caught, missed, hung or undecided.
- **side** (`Side`): A or B, one of the two revisions of a benchmark comparison.
  - **run** of a comparison: one measurement of one side; the runs of the two sides are interleaved.

**Docs, renames, examples**

- **citation**: a span in backticks of a doc that names a path, a glob or a dotted name; it must be tracked
  (`docs_check`).
- **passage** (`Passage`): a paragraph or a list item of a doc, as one text.
- **problem** (`Problem`): what the docs check reports: a citation that is missing or untracked, a long line, a rules
  file that would not load, or a decision off its form.
  - **form** of a decision (`decision_form`): its first sentence, the reasons of its rejected alternatives and its
    measurements in tables.
- **prose count** (`prose_counts.Count`): a count over its limit in a passage, which prompts a look in a review of the
  docs.
- **hit** (`Hit`, of a `HitKind`): a place a rename changes or lists.
- **rename** (`Rename`): the change of an identifier's name, or the move of a file.
- **example outcome** (`example_scripts.Outcome`): how an example ran or type-checked.

**Sessions and hooks**

- **transcript**: the JSONL file of a Claude Code session.
  - **record** (`Record`): one of its lines, parsed.
  - **answer to a prompt**: Claude's last text of the turn the prompt started.
- **subagent**: an agent a session starts for one task (`.claude/agents/`), with a transcript of its own.
- **context**: what one conversation holds: a session has that of its own conversation and one per subagent.
- **tool usage** (`tool_usage.Usage`): the calls of a tool in sessions and the size of their results.
- **token usage** (`token_usage.Tokens`): what a conversation was charged, weighted in units of one input token.
  - **API call** (`ApiCall`): one request of a conversation to the model; it sends the whole context again.
- **friction**: what cost a session round trips.
  - **friction event** (`friction.Event`, of a `Kind`): one piece of friction.
  - **friction log**: the file with a line per session and per retrospective.
  - **retrospective**: a look back at past sessions for their friction (skill `retro`).
- **hook event** (`HookEvent`): what Claude Code passes a hook.
  - **handler**: a function that takes the repository and a hook event and returns a hook result.
  - **hook result** (`HookResult`): what a handler returns: a block, a note or nothing.
  - **block**: a hook result whose message Claude must deal with.
  - **note**: a hook result with a message for the user or for Claude.
  - **dispatcher**: what runs every handler of an event.
  - **answer** of a hook: what the dispatcher gives Claude Code for an event.
- **memo** (`Memo`): what a hook remembers from one call to the next, lines in the state directory.
