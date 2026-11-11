"""Type-safe, declarative stream processing with shared pools.

Requires Python 3.14+, no third-party dependencies. Output order is NOT preserved.
Public API: `__all__` here (building and running pipelines) and of `strom.metrics` (observing runs),
`strom.testing` (testing pipelines) and `strom.backends` (backends of your own); all other names are internal.
Runnable examples are in examples/: simple.py, sqlite_rows.py (worker handles: a SQLAlchemy engine and a
model).

1. Quick start
==============

A pipeline is a stage built from stages. A stage maps each input item to zero or more output items,
and stages compose with `|`: Stage[A, B] | Stage[B, C] -> Stage[A, C]; the type checker rejects
stages that don't fit together. A run applies a stage to each item of its inputs and gives its
outputs as they come, as an async iterator.

    PIPELINE: Stage[int, Score] = (
        async_stage(fetch, concurrency=8)  # int                 -> Record
        | cpu_stage(parse, concurrency=2)  # Record              -> (id, list of words)
        | cpu_stage(score, concurrency=4)  # (id, list of words) -> Score
    )

    async def main() -> None:
        async with (
            Pools.open(cpu_workers=8, io_workers=16) as pools,  # reusable for several runs
            stream(PIPELINE, range(40), pools) as scores,
        ):
            async for score in scores: ...

    asyncio.run(main())  # sync code runs the async code like this, once

Running (async only; a `Pools` is always required):
    async with Pools.open(cpu_workers=..., io_workers=...) as pools:  the pools for the block
    async with stream(stage, inputs, pools) as outputs:              a run: its outputs as they come
  * `inputs`: an iterable or an async iterable. Pool sizes default to the hardware's,
    default_cpu_workers() and default_io_workers(): `Pools.open()` alone works.
  * Other backends (see Backends): `Pools.open_on(cpu=Processes(workers=8), io=Threads(workers=16))`.
  * What to do with the outputs is the consumer's code: a list (`[out async for out in outputs]`), a
    sum, a dict, or an effect per output. A cheap effect is the body of the `async for`; a blocking
    one is an io_stage (or cpu_stage) that returns what it did; effects at the same time are
    consumers in a TaskGroup inside the `async with` block sharing `outputs` (each output goes to one).
  * A generic stage passed directly (flatten(), duplicate(), identity(), first(f)) gets no type from
    the inputs: annotate it (`pairs: Stage[int, tuple[int, int]] = duplicate()`), or put a typed stage
    in front of it.

Factories: what a function is used for and where it runs (the prefix):
    stage          cheap, non-blocking functions, on the event loop
    async_stage    async iterables / coroutines, on the event loop
    io_stage       blocking IO, "io" pool
    cpu_stage      CPU-bound, "cpu" pool
  * io_stage streams an iterator: one pool task per item (the first also calls fn) and one finding the
    end, all on the thread that opened it (so fn may use thread-bound objects, such as a sqlite3
    connection it opens); a list or a tuple has nothing to stream and comes whole, in the one pool task
    that calls fn. cpu_stage collects all items of fn(item) in one pool task, so they arrive together; with the
    "process" backend, fn must be a top-level function and the items picklable, and a script needs an
    `if __name__ == "__main__":` guard: the pool workers import its module (see Backends).
  * Event-loop factories without a prefix and their special cases where(pred) (keeps the items for
    which pred is true), flatten() (unpacks iterable items) and identity() (x -> x) must not block.

Worker handles: setup and teardown for blocking functions (a connection pool, a client, a model):
    async with (
        Pools.open(cpu_workers=8, io_workers=8) as pools,
        worker_handle(engine_of, pools) as db,          # engine_of: a context manager factory (an opener)
        worker_handle(scoring_model, pools) as model,
    ):
        async with stream(io_stage(using(db, rows)) | cpu_stage(using(model, predict)), queries, pools) as out: ...
  * using(handle, fn) is a function of one input for any factory: `def rows(engine: Engine, query: str)
    -> Iterator[Row]` gets the handle first. It means `with engine_of() as h: fn(h, item)` per input,
    which is what the reference semantics, the event loop and `FromExecutor` do. On `Threads` and
    `Processes` a run shares one handle per process instead: one in the event loop's process for its
    threads ("io" and "cpu"), one in each worker process; it opens on its first use there (in a pool
    worker, never on the event loop) and is shared by every stage, thread and run using it.
  * At the end of its block the handle is closed in every process that opened it, after the uses in
    flight there; the block waits for that without blocking the event loop. Build the stages inside the
    block, from the handle (a use after the block fails); two blocks of one opener are two handles.
  * Shared by inputs and threads at once, a handle must be thread-safe and survive an input's error:
    pools, engines and clients are; a model if its library allows concurrent calls. What one input needs
    to itself, a connection, `fn` checks out from the handle per input (`with engine.connect() as conn:`).
  * On processes the opener (a top-level function, or a partial of one) is pickled, never the handle:
    each worker process opens its own (SQLAlchemy engines neither pickle nor survive `fork`).

Writing functions:
  * A stage's function returns an iterable of its outputs for one input (Stage[I, O]: 0..n outputs of
    type O per input of type I). A 1:1 function yields its one result
    (`def inc(x: int) -> Iterator[int]: yield x + 1`); a lambda, which cannot yield, returns a
    one-item list (`stage(lambda x: [x + 1])`); a function for an effect only returns nothing (`[]`).
  * For io_stage the form matters: a blocking 1:1 function returns a one-item list (`return [row]`, one
    pool task per input; a generator takes a second one to find its end), and a function that has all
    its items at hand returns them as a list (`return cursor.fetchall()`) rather than yielding them.

Concurrency:
  * `concurrency` of a step = max number of its input items in flight at once (default 1: one at a
    time), per occurrence of the step in a pipeline.
  * Pools are shared: ONE pool per resource ("io", "cpu") per `Pools`, no matter how many steps use
    it. Their sizes bound total resource use.

Failures: the first failing item stops the run, and the end of its block raises ONE ExceptionGroup
(a `RunFailed`) of the errors (rules: Reference, Failures); handle them with `except*`:
    try:
        async with stream(PIPELINE, range(40), pools) as scores:
            async for score in scores: ...
    except* ValueError as group:  # only the ValueErrors; any others propagate in a group of their own
        for error in group.exceptions:
            print(error, error.__notes__)  # e.g. bad item 3 ["in stage 'parse'"]

2. Combinators by task
======================

Working on pairs (product semantics):
  * first(f): (a, x) -> (b, x) for each output b of f on a; x passes through. second(f) likewise on
    the second element. Plumbing: swap() (a, b) -> (b, a), fst() (a, b) -> a, snd() (a, b) -> b.
  * product(f, g): (a, c) -> (b, d), f and g running at the same time. To apply two stages to the
    same item, duplicate it first: `duplicate() | product(f, g)`. Per input it emits the Cartesian
    product of the branch outputs (2 and 3 outputs give 6 pairs; none on one side, none): the same
    items as first(f) | second(g) (see Semantics).

Branching by a condition (sum semantics):
  * An item is tagged `Left(a)` or `Right(c)`: by tag_by(pred) (Left if pred is true), or by any
    stage emitting `Left`/`Right` values.
  * route(f, g) sends each tagged item to ONE branch: Left(a) to f, Right(c) to g; the outputs keep
    their tag (Left(b), Right(d)). left(f) = route(f, identity()) applies f to Left items only,
    right(g) = route(identity(), g) g to Right items only. untag() gives the value of either tag.
        tag_by(is_large) | route(io_stage(upload), stage(compress))  # Left: uploaded, Right: compressed

Collecting per input:
  * gather(f): ONE output per input: the list of f's outputs on it ([] if none, in no particular
    order), emitted once f holds no item of the input any more.

Repeating until done:
  * loop(f): a feedback loop: f emits Left(a) to continue with a (f is applied to it again) and
    Right(b) to output b. An input is complete once f holds no item of it any more; one whose Lefts
    never end never completes. E.g. paging through an API, `loop(io_stage(fetch_page))`:
        def fetch_page(url: str) -> Iterator[Left[str] | Right[Item]]:
            page = get(url)
            yield from (Right(item) for item in page.items)  # output each item
            if page.next_url:
                yield Left(page.next_url)                     # continue with the next page

3. Reference
============

Semantics:
  * A stage maps each input to a bag of outputs (1:0..n); a run applies it to every item of its
    inputs, and its outputs are the union of those bags. Composition `|` is associative with
    identity() as neutral element.
  * Correspondences: Stage[I, O] is conduit's ConduitT i o m () and pipes' Pipe; stream(stage,
    inputs) with its consumer is runConduit (yieldMany inputs .| stage .| consumer), a fold such as
    sinkList the consumer's code. product is Haskell's `***`, route `+++` (ArrowChoice).
  * Laws of stages equate outputs (as bags), not calls: product(f, g) calls g once per input,
    first(f) | second(g) once per output of f.

Resources vs. concurrency:
  * A run's inputs are iterated on the event loop (a sync iterable must not block; an async one may
    await) and belong to the caller: a run does not close them (`contextlib.aclosing` closes an async
    generator). Items made by a blocking function come from a stage of it on one input:
    `stream(io_stage(lambda _: read_rows()) | parse, [None], pools)`.
  * A slow consumer holds the run back (backpressure): a run takes only as many inputs as its queues
    hold.
  * `concurrency` of a step (see Quick start) also holds inside `product` and `route` branches and
    the bodies of `gather` and `loop`.
  * Event-loop steps without `async` (stage, where, flatten, identity, duplicate) never wait while
    handling an item, so they have no concurrency and no buffer setting: consecutive ones run as ONE
    step (see Fusion), and an output queue of such a step holds twice the concurrency of the part
    that takes its outputs (the next step; 1 for `product`, `route`, `gather`, `loop` and the
    consumer of a run), but never less than the default `buffer_size`. The queue of a run's inputs is
    sized the same way, for the stage's first step.
  * `product(f, g)` splits each pair and streams the parts through f and g as two independent
    streams, joined per input: both branches work at the same time, each step with its own
    concurrency; `product` itself has none. `route(f, g)` streams each input through one of
    its branches, likewise. A route takes its inputs one by one: while the queue into an input's
    branch is full (`buffer_size`), the inputs behind it wait, also those for the other branch.
  * `gather(f)` and `loop(f)` take their inputs one by one and have a `concurrency` of their own:
    the max number of inputs in flight, a gather's from taking it until its list is put, a
    loop's until f holds no item of it any more. It bounds the lists a gather keeps and the items
    a loop feeds back (only those of its inputs in flight; the newest item enters f first). Feeding
    back never waits, so the loop cannot block itself.
  * A step's task receives its input item first and only then submits to the pool, so idle
    tasks never occupy pool capacity.
  * Connection pools as worker handles (SQLAlchemy, psycopg's pool; for a driver without a pool, such
    as sqlite3, a small thread-safe pool of your own with `check_same_thread=False`):
        @contextmanager
        def engine_of() -> Iterator[Engine]:
            engine = create_engine(URL, pool_size=8, pool_timeout=5)
            try:
                yield engine
            finally:
                engine.dispose()

        def store(engine: Engine, row: Row) -> Iterator[int]:
            with engine.begin() as conn:  # a checkout and a transaction per input
                conn.execute(INSERT, row._asdict())
            yield row.id                  # emitted after the commit
    - No checkout may wait: a waiting checkout blocks a pool thread. A pool that grows on demand never
      waits; a bounded one lends at least the sum of the `concurrency` of the steps using it, over the
      runs at the same time (`pool_size=1` suffices in a "cpu" worker process running one call at once).
    - A transaction per input, in `fn`, outputs after the commit: a SQLAlchemy `Connection` begins a
      transaction on its first statement (also a read) and rolls it back when it closes uncommitted.
    - A pooled connection moves between threads from one input to the next (made by one thread, checked
      out by another, closed by a third): drivers with DB-API `threadsafety` 2 (psycopg, oracledb) and
      sqlite3 with `check_same_thread=False` (SQLAlchemy's default for SQLite) allow it. Within one input
      it stays put: an io_stage runs all items of an iterator on the thread that opened it.
    - Bound every wait: `sqlite3.connect(timeout=...)`, `statement_timeout`, `pool_timeout`.
  * Use a `Pools` within one event loop; several runs at once in it share its pools. At the end of
    the `Pools.open` or `Pools.open_on` block, each backend closes without blocking the event loop, also
    when the block is cancelled: the built-in ones cancel pool tasks not yet started and wait for
    running ones, in a thread.

Metrics (`help(strom.metrics)`):
  * stream(..., recorder=...) passes the events of a run to a recorder, a function of an event. Without
    one (the default) nothing is measured: no clock is read and no event is created (checked once per run).
  * `strom.metrics.StatsRecorder` aggregates ONE run into statistics (`recorder.stats()` after the run: a
    printable table, a row per step occurrence), and `diagnose(stats)` derives hints from them (the step
    that limits throughput, pool tasks waiting). The events, for a recorder of your own: see there.

Fusion (streaming runs; an optimisation that keeps the meaning):
  * Consecutive event-loop steps, also lifted ones and inside `product` and `route` branches, run
    as ONE step, a group named by their chain (e.g. `dup | neg`), with no task and no queue between
    them. Steps that wait, `product` and `route` are boundaries.
  * A group is reported as that one step: one occurrence in the metrics (one `StepId`, one
    position), and its errors are noted with its name ("in stage 'dup | neg'"); the traceback
    shows the function that failed.
  * A group whose steps drop many items (e.g. a filter after a 1:n step) regularly lets other
    tasks run.

Order:
  * Outputs are a bag: no order is promised in general. With concurrency=1 for every step, the
    output order is that of a sequential, depth-first evaluation (per input, in the order of
    `inputs`) - this is tested -
    except that `product` emits the pairs of one input as the results of its branches arrive,
    `route` the outputs of its two branches as they arrive, `gather` the lists as their inputs
    complete, and `loop` the outputs as they leave its body.

Failures (see Quick start for handling them):
  * The block of `stream` is the run's scope, as the block of an asyncio TaskGroup is: a failure
    cancels the block at its next `await`, and the block's end raises ONE ExceptionGroup ("pipeline run
    failed", a `RunFailed`) of the errors that ended the run, even of a single one, also of an error of
    the block (alone or with the run's). Each error is the one raised (a user's own exception group
    stays whole); an error of the run carries a note "in stage '<name>'" per stage it passed (none for
    an error of iterating `inputs`). KeyboardInterrupt and SystemExit propagate on their own; a
    cancellation from outside raises CancelledError; leaving the block early (`break`, `return`) stops
    the run without an error.
  * A failed run delivers no further outputs: its consumer is cancelled at its next `await` (at the
    latest when it asks for the next output); the end of the outputs is never a failure in disguise.
  * Consume the outputs inside the block, in its task or in tasks of a TaskGroup inside it (however
    deeply nested): they are cancelled with the run. A consumer outside it gets RuntimeError once the
    block of a failed run has ended, and so does any use of the outputs after the block.
  * Pool tasks of a failed run that have not started yet do not start: on threads from the moment the
    failing function raised; on processes one that a worker takes before the failure has reached the
    event loop may still start. Pool tasks already running finish (threads cannot be interrupted,
    processes are not killed). Other backends: see Backends.
  * Generators of stage functions are closed as soon as their consumer stops (not `inputs`, which
    belongs to the caller). io_stage closes those its run left (stopped early, or opened by a pool task
    after its step was cancelled) at the run's end, on the thread that opened them, after the pool
    task still running there, without waiting (errors of those closes are ignored); closing the pools
    runs such closes that are still queued.
  * A worker process that crashes fails the pool task it ran (`BrokenProcessPool`, which ends the run)
    and is replaced for the next one; the other workers go on. One that ended while idle (killed, or
    interrupted with Ctrl-C) fails nothing: its next pool task starts another process.
  * Worker handles survive an input's error (other inputs share them; the input's own `with` blocks,
    its connection and transaction, exit with it). A failing opener fails its input, with the note
    "opening its handle (<name>)", and the next use opens again; a use after the block fails its input
    ("worker handle '<name>' is closed"). The errors of the closes at the block's end are raised there
    as ONE ExceptionGroup, a note per process (chained to an error of the block's body); `__exit__` gets
    no error, as the block may have outlived several runs. A crashed process's handle died with it.
  * Pool tasks run at most once: a backend never retries a function.

From sync code (scripts, tools, notebooks without top-level `await`):
  * One `asyncio.run(main())` around an async `main` that opens the pools and runs the stages.
  * Several runs from sync code with one event loop and one `Pools` (e.g. a benchmark's rounds):
        with asyncio.Runner() as runner:
            stack = contextlib.AsyncExitStack()  # keeps the pools open across `runner.run` calls
            pools = runner.run(stack.enter_async_context(Pools.open(cpu_workers=4, io_workers=8)))
            try:
                for inputs in batches:
                    outputs = runner.run(to_list(stream(PIPELINE, inputs, pools)))
            finally:
                runner.run(stack.aclose())
    where `async def to_list(run)` is `async with run as outputs: return [o async for o in outputs]`.
    A `Pools` belongs to one event loop: not to several `asyncio.run` calls.

Testing (`help(strom.testing)`):
  * evaluate(stage, inputs): the reference semantics, sequential and deterministic; bag(items) compares
    outputs without order (each item as a whole: sort the list of a `gather` in a following stage first);
    `await check_against_reference(stage, inputs, pools)` compares a run with `evaluate`; check_backend /
    check_streaming_backend check a backend of your own.
  * A failed run raises `RunFailed`: `pytest.raises(RunFailed)`, or `pytest.RaisesGroup` for its errors.

Backends: what runs the pool of a resource, one per resource and `Pools`, created on first use.
  `Pools.open(cpu_workers=..., io_workers=..., cpu_backend=...)` is short for
  `Pools.open_on(cpu=Processes(...) or Threads(...), io=Threads(...))`; the `cpu_backend` (`CpuBackendKind`):
    "process" -> Processes: worker processes (any package; pickling + process startup cost)
    "thread"  -> Threads: threads of this interpreter; parallel only on the free-threaded build
                 (python3.14t), `Pools.open` warns otherwise (`Pools.open_on` takes the choice as made)
  `PoolConfig(cpu=..., io=...)` (the type of `pools.config`) holds a backend config per resource, a
  callable that creates the backend:
    Threads(workers=n)            threads of this interpreter; "cpu" or "io"
    Processes(workers=n)          processes; "cpu" only
    FromExecutor(factory=f)       any `concurrent.futures.Executor` f() creates (InterpreterPoolExecutor,
                                  Dask's `client.get_executor`, ...); "cpu" only; replaced by a new f()
                                  when it breaks (`BrokenExecutor`), shut down when the pools close
    a backend of your own         any callable returning a `strom.backends.Backend` (see there), e.g. one
                                  of remote workers; "io" needs a `StreamingBackend`; check it with
                                  `strom.testing.check_backend` (`check_streaming_backend`)
  "io" streams iterators that stay in the pool worker that opened them, so it takes only a backend
  that routes calls to that worker (the type checker rejects `io=Processes(...)`). How they differ:
                         Threads              Processes               FromExecutor           of your own
    io_stage             yes: an iterator     no (type error)         no (type error)        if it routes the
                         stays on its thread                                                 calls
    lambdas, closures    yes                  no: picklable           as its executor        without shared memory:
                                              functions               needs                  picklable functions
    after a failure      queued tasks do      queued tasks do not     queued tasks are       queued tasks are
                         not start            start (see Failures)    cancelled; those it    cancelled; dispatched
                                                                      dispatched may run     ones may run
    an iterator's close  on its thread        -                       -                      in its worker, best
                                                                                             effort
    a worker handle      one per process      one per worker process  per input              per its `close_handle`
    a crashed worker     -                    fails its pool task,    as its executor        as it reports it
                                              is replaced             reports it
  The results of a run are the same on every backend.

Architecture and conventions (for working on the package): `ARCHITECTURE.md` in the repository.
"""

from strom._interpreters.failures import RunFailed
from strom._runners import stream
from strom._runtime.executor_backend import FromExecutor
from strom._runtime.pools import CpuBackendKind, PoolConfig, Pools, default_cpu_workers, default_io_workers
from strom._runtime.process_backend import Processes
from strom._runtime.thread_backend import Threads
from strom._runtime.worker_handles.worker_handle import WorkerHandle, using, worker_handle
from strom._stages.combinators import first, gather, left, loop, product, right, route, second
from strom._stages.factories import (
    async_stage,
    cpu_stage,
    duplicate,
    flatten,
    fst,
    identity,
    io_stage,
    snd,
    stage,
    swap,
    tag_by,
    untag,
    where,
)
from strom._stages.model import Left, Right, Stage

__all__ = [
    "Stage",
    "CpuBackendKind",
    "PoolConfig",
    "Pools",
    "Threads",
    "Processes",
    "FromExecutor",
    "default_cpu_workers",
    "default_io_workers",
    "worker_handle",
    "WorkerHandle",
    "using",
    "stage",
    "async_stage",
    "io_stage",
    "cpu_stage",
    "where",
    "flatten",
    "identity",
    "swap",
    "fst",
    "snd",
    "untag",
    "duplicate",
    "first",
    "second",
    "product",
    "Left",
    "Right",
    "route",
    "left",
    "right",
    "tag_by",
    "gather",
    "loop",
    "stream",
    "RunFailed",
]
