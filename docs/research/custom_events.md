# Custom recorder events – strom

Research of 2026-11-15: how a user could define events of their own, emit them from the functions of their stages and
process them in a recorder of their own. For: a decision on the metrics API. Every design below adds public names, which
need the user's go-ahead; the chosen one becomes a plan. Searched: the documentation, changelogs and issue trackers of
pipeline, workflow and instrumentation libraries. Subagents read the sources, one per page or per question; each entry
under Sources says how it was read, and those marks were not checked a second time. The designs were run on the library
of this date, with stand-ins for the proposed names (Probes).

## Answer

- **The event.** One new kind in `Event`, called `Emitted` here: the step, the time and the user's value as
  `payload: object`. A custom event is then any class of the user's, and a recorder selects it with a class pattern,
  which narrows the payload for mypy, pyright and ty (probed). It needs no base class, no registry and no type parameter
  on `Recorder`.
- **Emitting.** Three ways fit strom. E1: the function yields an event as `Left` and an output as `Right`, and
  `recorded(f)` sends the events to the run's recorder, as `loop(f)` feeds its `Left` values back. E2: an ambient
  `emit(payload)` that finds the run through a `ContextVar`. E3: `emitting(fn)` passes `emit` to the function as its
  first parameter, as `using(handle, fn)` passes a handle.
- **Recommended.** `Emitted` with E1, and E3 on top of it as a recipe or a second name. Events are then data: typed at
  the function, tested without a run, carried by every backend with the outputs, and recorded by library code, so the
  recorder's contract holds unchanged. E3 spares the function the `Right` around every output, the kind of wrapper
  Dagster's users objected to (finding 2.2). E2 is what a user of logging or OpenTelemetry expects and leaves signatures
  alone, but it needs a target set in every pool task, a rule for a recorder's error inside the user's function, and it
  reports events of work that then fails (findings 2.4, 2.5, 3.3, 4.1).
- **Today.** Without any change a function can already yield tagged events and an event-loop stage can hand them to an
  object of the user's (E0, probed). What the library would add is the one channel `recorder=`: the step id and the
  time, the order with the run's own events, `combine_recorders`, and one switch that turns recording off.
- **How well supported.** The shapes and their pitfalls come from the docs, the source and the issue trackers of the
  libraries. What the type checkers accept and what an event costs are measured here, on one machine. No source compares
  the ways by measurement, and no library that was read delivers the events of a worker with the guarantees of strom's
  recorder (finding 3.2).

## Today

- `Event` is a closed union of five final classes and `Recorder` a function of one event. The contract lets `Event` gain
  kinds, so a recorder ends its `match` with `case _: pass`. `StatsRecorder` does not: it raises on a kind it does not
  know (`assert_never`), which the stand-in event showed.
- A stage's function gets its input and nothing of the run. A pool task brings back its result and, when the run
  records, two durations measured in the worker (`_timed` in `strom._interpreters.offloaders`).
- A `ContextVar` set around `stream(...)` is visible in the functions of `stage` and `async_stage`, which run in the
  step's task (probed). In a function of `io_stage` it is not: on the default build a pool thread starts with an empty
  context, and on the free-threaded build it keeps the context of the code that started it, so the second run saw the
  value of the first (probed; `docs/todo.md`, B11).

## Findings

### 1. What a custom event is for its handler

**1.1 Three shapes are in use.** A name with maps of values: `execute(EventName, Measurements, Metadata)` with a list of
atoms and two maps [18]; a span event of "Name of the event", a timestamp and attributes [24]; `sys.audit(str, *args)`,
whose hook gets the name and a tuple [22]; a type string with JSON fields [26]; a topic with a message [17]; an event
name with a resource and an "Open-ended set of data describing what happened" [27]. A class of the user's: a subclass of
`jdk.jfr.Event` whose fields are the event's data [19]. The handler's own type narrowed to the user's: "any
`Tracer m Text` can stand in where a `Tracer m Event` is required", by `contramap` [21]. Trio's `Instrument` has fixed
hook methods and no events of the user's [23]. For strom: `match` gives the second shape without a base class, because a
class pattern narrows an `object` (probed). The first shape is what an exporter needs, and it derives from the second:
the class's name and its fields.

**1.2 A component takes the most specific handler type and the caller adapts.** Programs should take "as specific a
tracer as possible" [21]. For strom: `Recorder` is a function, so a recorder that handles only the user's payloads is a
function composed in front of it. That needs no library support beyond `combine_recorders`.

**1.3 The envelope with one untyped payload is an established shape, with one warning.** .NET's `DiagnosticSource` hands
a subscriber "exactly one `object` as a payload", advises "CONSIDER creating an explicit type for the payload" and
warns: "once you expose the payload type you must keep it forever" [35]. For strom: the payload classes are the user's
own, so that promise is the user's to make, not the library's.

**1.4 No Python library that was read checks the link between a user's event and its handler.** Textual dispatches a
subclass of `Message` by the handler's name or by `@on(Button.Pressed)`, whose signature does not relate the message
type to the handler's parameter [28]. Django's receivers take `**kwargs` because "at any point arguments could get added
to the signal" [29]; blinker, SQLAlchemy and structlog pass `Any` [30]; Eliot's `MessageType` is validated "in your unit
tests" only [31]. What the checkers do check is the class pattern (Probes, a subagent's): it narrows an `object` payload
in all three, and never exhausts it, since "Exhaustiveness checking is based on type narrowing" and not on attributes
[33]. A misspelt field in a class pattern is reported by mypy, by pyright only for a `@final` class and by ty not at
all; at run time such an arm never matches, because on an `AttributeError` "the class pattern fails" [32]. For strom:
the closing `case _` stays, and a payload class is best `@final`.

**1.5 A base class for the user's events is a second API.** Textual changed it twice in breaking releases: "Messages
don't require a `sender` in their constructor" (0.14.0) and "The `@on` decorator will now match a message class and any
child classes" (0.28.0) [28]. For strom: speaks for carrying the user's value in an event of the library's instead of
deriving the user's class from one.

**1.6 Making the handler's type generic in the user's events works, and takes back what the contract allows.** With a
default for the type parameter, `type Event[U = Never]` as the union of the built-in kinds and `U` checks in all three
checkers, and a flat `match` over it is exhaustive [32, PEP 696] (Probes, a subagent's). An exhaustive match then fails
to check in every recorder of a user when the library adds a kind, the break Rust's `non_exhaustive` exists for: "Adding
this new setting is now a breaking change!" [37]. An envelope generic in its payload meets a second obstacle: for a
class with `__slots__` and a `Final` attribute, strom's event style, pyright infers the parameter invariant where mypy
and ty infer it covariant [34]. For strom: `Event` "may gain kinds", so the payload stays `object`.

**1.7 A class restricts what a payload may hold as soon as it leaves the process.** JFR accepts primitives, `String`,
`Thread` and `Class` as field types, and other types "are silently ignored" [19]; Celery's fields "Must be JSON
serializable" [26]; .NET's `EventSource` "requires that only serializable data be logged", unlike the in-process
`DiagnosticSource` [35]; a numpy scalar in a Dask event killed the worker [41, issue 7471]. For strom: a payload emitted
in a worker process is pickled with the result, by its qualified name. Its class is therefore defined "at the top level
of a module" [38], the rule that holds for the items of a `cpu_stage`.

### 2. Data in the outputs, or a call on a context

**2.1 Libraries offer both and give them different jobs.** The data path carries what is typed, ordered with the outputs
and committed with the work: Beam's tagged outputs [4], Flink's side outputs through a typed `OutputTag` [9], Dagster's
yielded events [1]. The call on a context carries observations, best effort: Beam's `Metrics` [4], Flink's
`getRuntimeContext().getMetricGroup()` [9], Dagster's `context.log_event` [1], Spark's accumulators [14]. Beam's Python
SDK tags an output with a string, and its type hints did not follow: a step downstream "requires `Dict[str, Any]` but
got `Union[Dict[str, Any], TaggedOutput]`" [8]. For strom: `Left` and `Right` are types, so the stage after
`recorded(f)` is checked.

**2.2 The one documented switch was made for the function's shape, not for its meaning.** Dagster 0.14.0 added
`context.log_event` because yielding "caused lint errors for many users, made it difficult to add mypy types to ops, and
also forced usage of the verbose Output API" [2]; a solid that yielded an event without an `Output` failed [3]. A user
of Flink objected likewise that a stream of events "mixes metrics collection with application logic" [10]. For strom: a
stage's function returns an iterable already, so "must become a generator" does not carry over. The forced wrapper does:
with `Left(event)` every output needs `Right`.

**2.3 Keeping both ways needs a rule for their order.** Dagster queues logged events on the context and flushes them
"based on the outputs that they happen between"; a reviewer: "So it's a result of supporting both yield and log" [3].
For strom: one way to emit, or the order between the two is part of the contract.

**2.4 An ambient call is bound to the thread the library manages, and elsewhere it is dropped in silence.** Beam's Java
SDK keeps the metrics container in a `ThreadLocal` and logs once "Unable to update metrics on the current thread"; its
Python updater does nothing without a current tracker [5]. A counter incremented in a thread of the user's own pool is
not counted (BEAM-13379); "there's no good workaround ... would probably work poorly with threadpools" [7]. Temporal:
"new threads starting inside of activities must `copy_context()` and then `.run()` manually" [15]. For strom: this is
the state of Today; an ambient `emit` in a pool task works only if the pool task installs its target itself.

**2.5 What an ambient call reports is not tied to the fate of the work.** Reporting from workers "can overcount when
retrying and may be under the actual attempts"; the alternative is "something like a side output where the counts are
committed as part of each bundles results ... more accurate" [6]. Spark: an update "may be applied more than once if
tasks or job stages are re-executed" [14]. For strom: a pool task runs at most once, so nothing is counted twice. The
other half carries over: an emitted event reports work of an input that then fails, and a yielded one shares the fate of
its outputs.

**2.6 A tap passes items through and its callback's error ends the stream.** RxJS: the result "is an exact mirror of the
source", except that an error in the handler "will be emitted as an error from the returned observable" [11]. Reactor's
`tap`: an exception "causes the subscription to be cancelled" [12]. Pekko's `wireTap` drops instead: "If the wire-tap
`Sink` backpressures, elements that would've been sent to it will be dropped" [13]. For strom: a stage that records and
passes on is such a tap, and the recorder's contract is the first behaviour (`docs/decisions/recorder.md`).

**2.7 The explicit variant of the call passes the context as an argument.** Go: `Log(ctx, category, message)`, and "Log
messages and regions are attached to the task, if any, in the Context passed" [20]. Beam's Go SDK: the context "must be
passed to the metric or the metric value will not be recorded" [4, relayed]. For strom: this is E3.

### 3. From a worker to the handler

**3.1 Single events travel over a channel beside the results; what comes back with a result is a completion or a
total.** Dask's `log_event` schedules a callback on the worker's loop, batches messages for 2 ms towards the scheduler,
which keeps a bounded queue per topic and passes them to subscribed clients [41]. Celery publishes to the broker [26],
logging puts records on a queue that a listener thread reads [42], Ray tails the workers' log files [44]. tqdm and
joblib count in the parent when a task completes, Spark merges a task's updates at its end, Beam's committed metrics
come with each bundle's result [43] [14] [6]. For strom: a backend promises `run(fn, arg)` and nothing else, so a
channel would be a new part of the contract of `strom.backends`. What the function returns, or what a wrapper around it
returns with the result, crosses every backend today.

**3.2 No channel that was read gives what the recorder's contract promises.** Dask's handler runs on the client's loop
with one argument, `(timestamp, msg)`; its exceptions are logged and swallowed, order holds per worker only, and when
the connection breaks "any messages in our buffer are lost" [41]. A `multiprocessing.Queue` pickles in a feeder thread:
an item put right before `os._exit` was lost (a subagent's probe) [39]. Ray warns that "Performance may be poor if there
are more than a couple thousand updates per second" [44]. A callback scheduled with `call_soon_threadsafe` from a pool
thread is not ordered against the task's result: the awaiter of `run_in_executor` resumed before the callback ran in
8415 of 20000 runs on the free-threaded build and in 1 of 20000 on the default one, and an error in the callback goes to
the loop's exception handler, not to the awaiter (a subagent's probe on 3.14.8) [39]. For strom: "in the order they
happen" and "a recorder's error ends the run" hold for what arrives with a result, not for a bare channel.

**3.3 A pool thread does not get the caller's context, and on the free-threaded build it gets a stale one.**
`asyncio.to_thread` copies the context per call; `loop.run_in_executor` and `ThreadPoolExecutor.submit` do not [39].
Copying in `run_in_executor` was declined because a process pool cannot follow: "We can't have a single api that
sometimes works with contextvars and sometimes doesn't" [40]. Since 3.14 a thread starts with a copy of the context of
the caller of `start()` if `sys.flags.thread_inherit_context` is set, which is the default on the free-threaded build
only [16]. Dask reads its current worker from a `ContextVar` that a copy carries into the pool thread, and its code says
of process executors: "Can't capture contextvars across processes" [41]. For strom: see Today. An ambient "current step"
would attribute the events of one run to another unless each pool task sets it.

**3.4 An event of a worker process reaches the parent only as data.** OpenTelemetry's threading instrumentation captures
the context at `submit` and has nothing for process pools; a context propagated into a process yields a span whose
`add_event` does nothing [45]. Logging's `QueueHandler.prepare` formats the record and clears its arguments, so only
strings travel [42]. A failed task of a `ProcessPoolExecutor` sends only its exception, which keeps its notes and
attributes (a subagent's probe) [39]. For strom: an exporter that nests worker events under a span of the parent
(`docs/todo.md`, B17 and B18) gets them from the events of the run, whichever design emits them.

### 4. A handler's error, and the cost when nobody listens

**4.1 Libraries choose between three answers to a failing handler.** Remove it: "When a handler fails, it is removed and
a failure event is emitted" [18]; Trio logs the exception and disables the instrument [23]. Never raise: "API methods
MUST NOT throw unhandled exceptions when used incorrectly by end users" [24]. End the program: "later hooks are ignored
and *in general* the Python runtime should terminate" [22]. For strom: decided, a recorder's error ends the run
(`docs/decisions/recorder.md`). With an ambient `emit` that error is raised inside the user's function, which may catch
it: a case the contract does not cover yet.

**4.2 Every such API has a guard against computing what nobody records.** JFR: "Gathering data to store in an event can
be expensive. The `shouldCommit()` method can be used to verify whether an event instance would actually be written"
[19]. OpenTelemetry: `IsRecording` "SHOULD be used to avoid expensive computations of a Span attributes or events" [24].
Rust's `tracing`: without an interested subscriber the event "will never be constructed" [25]. contra-tracer: with
`nullTracer` the calls stay in the program at "zero runtime cost" [21]. PEP 578: "Ideally, each argument is a reference
to existing data rather than a value calculated just for the auditing call" [22]. Go's `slog` shows why a guard is
needed where arguments are not lazy: "The arguments to a log call are always evaluated", also for a disabled level [36].
For strom: "an optional feature must cost nothing when it is off" (`ARCHITECTURE.md`) asks for the same. Measured:
Probes.

**4.3 Handlers run in the emitting thread and must not block.** "The `handle_event` callback of each handler is invoked
synchronously on each `telemetry:execute` call. Therefore, it is extremely important to avoid blocking operations" [18].
A run with over 2000 `log_event` calls, each stored singly, was slow [3, issue 19618]. For strom: the contract of
`Recorder` says the same, and a chatty emitter makes it matter.

## Designs

### The event, for every design

A custom event is a class of the user's. The library carries it in one new kind of `Event`:

```python
@final
class Emitted:
    """The user's code at `step_id` emitted `payload`, recorded at `emitted_at`."""

    step_id: StepId
    emitted_at: float
    payload: object


@dataclass(frozen=True, slots=True)
class PageFetched:  # the user's: top-level and picklable if a worker process emits it
    url: str
    num_items: int
    fetch_time: float


@dataclass(frozen=True, slots=True)
class Retried:
    url: str
    attempt: int


class FetchReport:  # a recorder of the user's own
    def __init__(self) -> None:
        self.num_items: Counter[str] = Counter()
        self.retries = 0

    def __call__(self, event: Event) -> None:
        match event:
            case Emitted(payload=PageFetched(url=url, num_items=num_items)):
                self.num_items[url] += num_items
            case Emitted(payload=Retried()):
                self.retries += 1
            case _:  # the run's own events, and the events of other code
                pass


report, stats = FetchReport(), StatsRecorder()
async with stream(PIPELINE, urls, pools, recorder=combine_recorders(stats, report)) as scores:
    ...
```

- The checkers infer `url: str` and `num_items: int` in the first arm (`assert_type`, probed with all three).
- A payload class is best `@final` and its recorder tested: a misspelt field in a pattern is an arm that never matches,
  and only mypy reports it for every class (finding 1.4).
- `StatsRecorder` gets an arm that ignores the kind; `combine_recorders` passes it on as it is.
- The contract of `Recorder` gains two sentences: where an `Emitted` stands among the events of its step, and that its
  payload is the user's.
- An exporter (`docs/todo.md`, B17) maps it to a span event: the payload's class name, its fields as attributes.
- A recorder of many payload classes can look its handler up by `type(event.payload)`: a `match` reached its seventh arm
  after about 0.7 µs, a dict of types answered in 0.1 µs (Probes).

Not proposed for the event:

- A base class to subclass (JFR [19], Textual [28]). The library would set the step and the time on the user's object, a
  payload could no longer be a plain value, and the base class would be an API of its own (finding 1.5).
- The user's classes as members of the union, `Recorder[U]` with `Event[U]` (finding 1.6). It makes a flat `match`
  exhaustive, at the price of a type error in the user's recorder for every kind the library adds later. It leaves no
  place for the step and the time. And no type connects `U` with what the stages emit, because `Stage[I, O]` has no
  parameter for it: the annotation would be a claim that nothing checks.
- An envelope generic in its payload, `Emitted[P]`. The same unchecked claim, and pyright infers `P` invariant for a
  class in the style of strom's events (finding 1.6).
- A third type parameter on `Stage` for the emitted type. It would run through every combinator and through what the
  three checkers infer for them (`.claude/rules/typing-api.md`).
- A name with a map of attributes [18] [24]. Nothing narrows a map by its name, and free-form messages "force consumers
  to deal with the mess" [41, issue 8688].
- Tags declared as values, like `OutputTag<T>` [9]. In Python the class is the typed tag, and `match` reads it.

### E0. Today's tools, no change

The function yields its events as `Left` and its outputs as `Right`. An event-loop stage built by the user hands the
events to an object of the user's:

```python
def recording_lefts[E, O](record: Callable[[E], None]) -> Stage[Left[E] | Right[O], O]:
    def split(tagged: Left[E] | Right[O]) -> Iterator[O]:
        match tagged:
            case Left(event):
                record(event)
            case Right(out):
                yield out

    return stage(split, name="record")


pipeline = io_stage(fetch_page, concurrency=4) | recording_lefts(report.fetched) | cpu_stage(score)
```

It runs on threads and on processes and passes the three checkers (probed). It lacks what `recorder=` gives: the events
do not reach the run's recorder, carry no step id or time, and the pipeline is built from the recording object, so it is
no constant.

### E1. `recorded(f)`: events as `Left` outputs (recommended)

`f` emits `Left(event)` to record the event and `Right(out)` to output `out`:

```python
def fetch_page(url: str) -> Iterator[Left[PageFetched] | Right[Item]]:
    started_at = perf_counter()
    page = get(url)
    yield Left(PageFetched(url, len(page.items), perf_counter() - started_at))
    for item in page.items:
        yield Right(item)


PIPELINE: Stage[str, Score] = recorded(io_stage(fetch_page, concurrency=4)) | cpu_stage(score)
```

- **Meaning.** The outputs of `recorded(f)` are the `Right` values of `f`. Its `Left` values go to the run's recorder as
  `Emitted`, in the order they arrive; without a recorder they are dropped. The reference semantics drops them too, so
  the laws equate what they equated. Events count calls, as `InputHandled` does.
- **Testing.** The events are outputs of `f`: `evaluate(io_stage(fetch_page), [url])` lists them with the items.
- **Backends.** Events cross to the event loop as items do, on every backend, also one of the user's own.
- **The recorder's contract.** Library code calls the recorder, in a step's task: its error ends the run with the stage
  note, like the error of any event of a step.
- **Spelling.** The combinator binds its type variables from its argument. A plumbing stage without arguments,
  `f | recorded()`, leaves them to the context: pyright reported an unknown type for it inside `loop(...)` (probed).
- **In a loop body** the body's own tags travel inside `Right`:

```python
def fetch_pages(url: str) -> Iterator[Left[PageFetched] | Right[Left[str] | Right[Item]]]:
    page = get(url)
    yield Left(PageFetched(url, len(page.items), 0.0))
    for item in page.items:
        yield Right(Right(item))  # output the item
    if page.next_url is not None:
        yield Right(Left(page.next_url))  # continue with the next page


PAGES: Stage[str, Score] = loop(recorded(io_stage(fetch_pages))) | cpu_stage(score)
```

Limits:

- An event costs what an item costs, also when nothing records: about 1 µs in an event-loop stage, 3 µs in a list of an
  `io_stage`, 23 µs yielded from a generator of an `io_stage`, where it is a pool task of its own (Probes). A function
  with many events returns them in a list, as the user guide says of items.
- The events of a `cpu_stage` arrive when its pool task ends, and those of a call that fails are lost with its outputs.
- The step id is that of the recording step, not of the step that yielded. After a pool step it is a step of its own,
  named `recorded` unless the user names it.

What it needs in strom: `Emitted`, the combinator, and a way for an event-loop step to reach the run's recorder. Either
a leaf kind of its own, with an arm in the four places that match leaves (`strom._interpreters.item_fns`,
`strom._interpreters.reference`, `strom._interpreters.fusion`, `strom._stages.display`); it would be a boundary of
fusion, since a fused group's function knows no run. Or a private `ContextVar` that a step's task sets, which is the
event-loop half of E2; the recording function is then an ordinary event-loop function and fuses.

### E3. `emitting(fn)`: `emit` as the function's first parameter

The function gets a callable and keeps its own output type:

```python
def fetch_next(emit: Callable[[PageFetched | Retried], None], url: str) -> Iterator[Left[str] | Right[Item]]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            page = get(url)
            break
        except TimeoutError:
            emit(Retried(url, attempt))
    else:
        raise TimeoutError(url)
    emit(PageFetched(url, len(page.items), 0.0))
    for item in page.items:
        yield Right(item)
    if page.next_url is not None:
        yield Left(page.next_url)


PAGES: Stage[str, Score] = loop(recorded(io_stage(emitting(fetch_next)))) | cpu_stage(score)

events: list[PageFetched | Retried] = []  # a test passes any callable
items = list(fetch_next(events.append, URL))
```

- `emitting(fn)` is a function of one input for any factory, like `using(handle, fn)`: it collects what `fn` emits and
  yields it as `Left` in front of the next output, and the outputs as `Right`. Nothing ambient: the parameter is the
  dependency (finding 2.7).
- The checker checks what the function emits against the parameter's type, and a test needs no run.
- It is E1 with an adapter of about a dozen lines, which a user can write today (probed). So it can ship with E1, later,
  or as a recipe in the user guide.
- An event waits for the function's next output or its end, so it is not live during a long wait. A callback of a client
  library can emit, which a `yield` cannot.
- Like `Using`, the adapter carries the function's name for the stage (the stand-in's stage was named `stage`).

### E2. `emit(payload)`: an ambient call

The function calls a function of the metrics module:

```python
async def download(url: str) -> AsyncIterator[Path]:
    async with client.stream("GET", url) as response:
        async for chunk in response.aiter_bytes():
            file.write(chunk)
            emit(Downloaded(url, len(chunk)))  # live: recorded before the function goes on
    yield path


def parse(path: Path) -> Iterator[Row]:  # a cpu_stage: recorded when its pool task ends
    rows = read_rows(path)
    if recording():  # the guard skips a payload that nobody records
        emit(Parsed(path.name, len(rows), histogram(rows)))
    yield from rows
```

- **Meaning.** An effect of the function, like logging: outside the laws and the reference semantics. Outside a
  recording run `emit` does nothing, so the function runs in a test and in `evaluate` unchanged.
- **On the event loop** a step's task sets a `ContextVar` to its emitter; `emit` reads it and records at once, with the
  step id and the task of the caller. The stand-in did this for `stage` and `async_stage` (probed).
- **In a pool task** the wrapper that times the function when the run records (`_timed`) would install a collector for
  the call and return what it collected with the result; the events are recorded after the task's `PoolTaskFinished`.
  This crosses every backend, and an unrecorded run pays nothing per pool task. Unprobed.
- **Cost of a call that records nothing:** about 45 ns, and 55 ns more for building the payload, which the guard saves
  (Probes).

It needs rules that E1 does not:

- A recorder's error is raised from `emit`, inside the user's function. If the function catches it, the run would go on
  with its failure flag set; the step has to raise the error again when the function next yields or ends.
- The collector must be set by each pool task and never inherited (finding 3.3). A call in a thread the function started
  itself is dropped in silence (finding 2.4).
- Events come back with the result of their pool task. A channel that delivers them while the task runs would give up
  the order against results and the recorder's error ending the run (finding 3.2).
- The events of a pool task that fails are lost unless they ride on its error. An attribute set on the error in a worker
  process arrives with it on the built-in backends (probed); the contract of a backend promises only its type, message
  and notes.
- The time of an event emitted in a worker is the arrival of its pool task's result, unless the wrapper measures offsets
  as it measures durations.
- A run started inside a stage's function must not inherit the emitter of the run around it.
- Nothing declares what a stage emits: the payload's type is `object` at the call as well.

It would revisit two decisions: the step id in a `ContextVar` was rejected as "implicit" for the offloader
(`docs/decisions/offloading.md`), and a module-level declaration was rejected for worker handles because setup and
teardown were invisible (`docs/decisions/worker-handles.md`).

### The designs side by side

|  | E0 today | E1 `recorded` | E3 `emitting` | E2 `emit` |
| -- | -- | -- | -- | -- |
| New public names | none | `Emitted`, `recorded` | E1 and `emitting` | `Emitted`, `emit`, `recording` |
| The function's signature | outputs tagged | outputs tagged | `emit` first | unchanged |
| Events typed at the function | yes | yes | yes | no |
| Reaches `recorder=` | no | yes | yes | yes |
| Step id of | none | the recording step | the recording step | the emitting step |
| Live on the event loop | yes | yes | at the next output | yes |
| From an `io_stage` | per item | per item | with the next output | with the next result |
| From a `cpu_stage` | at the task's end | at the task's end | at the task's end | at the task's end |
| Before a failure, `cpu_stage` | lost | lost | lost | lost, or on the error |
| Not recording, per event | an item | an item | an item | 45 ns and the payload |
| Tested without a run | yes | yes | yes | no |
| Ambient state | none | none, or private | none, or private | yes |

### Not covered

- Events of the consumer, the body of the `async with`: it holds its recorder and calls it.
- Events of a backend of the user's own: a backend knows no runs (`ARCHITECTURE.md`, Concurrency and pools).
- Sampling, levels and filtering by name: a recorder's code.

## Probes

Run on 2026-11-15 with Python 3.14.8, the suite's venv and the tox environment of the free-threaded build; scripts in
the session's scratchpad, not kept. Those marked "a subagent's" were run by a research subagent and not repeated.

- **Types.** A stand-in `Emitted` with `payload: object` and a recorder with nested class patterns; E0; a stand-in
  `recorded(f)` and `emitting(fn)` in a `loop`: clean in mypy (strict, `--disallow-any-expr`), pyright (strict) and ty.
  The spelling `f | recorded()` inside `loop(...)`: an unknown argument type in pyright, clean in the other two.
- **Types, a subagent's** (mypy 2.4.1, pyright 1.1.414, ty 0.0.91). `assert_never` on an `object` payload after its
  class patterns fails in all three. A misspelt field in a class pattern: reported by mypy, by pyright only for a
  `@final` class, by ty not. A type alias with a default, `type Event[U = Never]`, and a flat exhaustive `match` over
  it: clean in all three. A generic class with `__slots__` and a `Final` attribute: covariant for mypy and ty, invariant
  for pyright.
- **Runs.** E0, E1 and E3 on `Threads` and `Processes`, and E2 on the event loop through a `ContextVar` set around the
  run: every event arrived, the outputs were unchanged. Today's `StatsRecorder` raised on the stand-in kind.
- **Contexts.** A `ContextVar` set around each of two runs on one `Pools`, read in an `io_stage` function: the default
  build read the default both times (`sys.flags.thread_inherit_context` is 0), the free-threaded build read the first
  run's value both times (the flag is 1).
- **Errors.** An attribute set on a `ValueError` in a function arrived with the error from a process and from a thread.
- **Costs**, pinned to the twelve performance cores, two runs that agreed within 5%:

| A call that records nothing (best of 5) | ns |
| -- | -- |
| an empty lambda | 17 |
| `emit(None)`, through a lambda | 45 |
| `emit(Payload(1))` | 102 |
| `recording() and emit(Payload(1))` | 48 |
| `LOG.debug("x %s", 1)`, disabled | 100 |

| A run without a recorder, a step and an event-loop stage (median of 7) | µs per input |
| -- | -- |
| `stage`, one output | 3.9 |
| `stage`, one event and one output, the event dropped | 4.8 |
| `io_stage` returning a list, one output | 26.7 |
| `io_stage` returning a list, one event and one output | 29.8 |
| `io_stage` generator, one output | 47.8 |
| `io_stage` generator, one event and one output | 70.9 |

A subagent's, unpinned, one run each:

| Dispatch of one event, with the call of its handler | ns |
| -- | -- |
| `match`, the first arm | 119 |
| `match`, the fifth arm | 285 |
| `match`, the seventh arm, flat | 363 |
| `match`, the seventh arm, an envelope with a nested payload | 659 |
| a dict by `type(event)` | 114 |

| Pickling and unpickling an event of one field | µs |
| -- | -- |
| a plain class with `__slots__` | 7 |
| a frozen dataclass with slots | 11 |
| a tuple of a name and a dict | 2.4 |

## Not found, not checked

- A measurement in another library of either way's cost without a listener, or of a live channel's overhead: only
  mpire's "The overhead is very minimal" [43] and Ray's warning [44].
- A library that delivers the events of a worker to a handler in the parent in order against the results, with the
  handler's error failing the job.
- A Python library whose types tie a user's event class to its handler.
- The checkers' own documentation of class patterns on an `object` subject: the behaviour above is measured.
- A maintainer's statement on pyright's variance for a class with `__slots__` [34].
- Dagster: a reason for `log_event` beyond the changelog's sentence, and what happens to logged events when the op then
  fails.
- Flink: guidance on when to use a side output and when a metric.
- Beam: a definition of attempted and committed metrics in the guide; which runners support committed ones.
- Dask: a statement on the order or the delivery of events; whether a subscription replays the events kept before it
  (the code shows no replay; not tested).
- Unprobed: E2 in pool tasks (the collector), the recorder's error raised from `emit`, a recording step as a leaf kind.
- RxJS: the page of `tap` (rendered by JavaScript); its source on the branch 7.x was read instead.

## Sources

Read: "full", "sections" (those named), "extract" (through the fetch tool's quotes, not checked against the page),
"relayed" (a quote or summary passed on by a tool or another author).

01. Dagster. Op events (docs of 1.13.30). https://dagster.io/docs/guides/build/ops/op-events — extract.
02. Dagster. Changelog, 0.14.0. 2022. https://raw.githubusercontent.com/dagster-io/dagster/1.0.0/CHANGES.md — the entry,
    full.
03. Dagster. Issues 4227 (2021), 5975 (2021), 19618 (2024); pull requests 6304 and 6359 (2022).
    https://github.com/dagster-io/dagster/pull/6304 — full; of 6304 the body and the review.
04. Apache Beam. Programming Guide, 4.5 and 10. https://beam.apache.org/documentation/programming-guide/ — sections; the
    Go SDK's package metrics, relayed.
05. Apache Beam. The Java classes MetricsEnvironment and MetricResult, the Python module of metrics execution.
    https://github.com/apache/beam — sections.
06. Chambers. Re: Committed vs. attempted metrics results. dev@beam, 2017.
    https://www.mail-archive.com/dev@beam.apache.org/msg00240.html — full.
07. Zhang, Bradshaw. Updating Metrics Counter in user defined thread. dev@beam, 2020.
    https://www.mail-archive.com/dev@beam.apache.org/msg18408.html — full; BEAM-13379 (2021),
    https://issues.apache.org/jira/browse/BEAM-13379 — full.
08. Apache Beam. Issue 26493. 2023. https://github.com/apache/beam/issues/26493 — full; the pull request that closed it
    not read.
09. Apache Flink. Side Outputs; Metrics (docs of 2.3).
    https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/side_output/ — extract; of Metrics the
    sentence on `getRuntimeContext()`, the rest relayed.
10. Schepler. Answers on user@flink, 2017 and 2019. https://www.mail-archive.com/user@flink.apache.org/msg27046.html —
    full.
11. RxJS. The docstring of `tap`, branch 7.x. https://github.com/ReactiveX/rxjs/blob/7.x/src/internal/operators/tap.ts —
    full.
12. Reactor. The Javadoc of `Flux.doOnNext` and `Flux.tap`.
    https://github.com/reactor/reactor-core/blob/main/reactor-core/src/main/java/reactor/core/publisher/Flux.java —
    sections.
13. Apache Pekko. The operators wireTap and log.
    https://pekko.apache.org/docs/pekko/current/stream/operators/Source-or-Flow/wireTap.html — extract.
14. Apache Spark. RDD Programming Guide, Accumulators.
    https://spark.apache.org/docs/latest/rdd-programming-guide.html#accumulators — sections.
15. Temporal. README of the Python SDK. https://github.com/temporalio/sdk-python/blob/main/README.md — sections.
16. CPython 3.14. `threading.Thread`, `asyncio.to_thread`.
    https://docs.python.org/3.14/library/threading.html#threading.Thread — sections.
17. Dask. Logging, Structured logs (docs of 2026.8.0). https://distributed.dask.org/en/stable/logging.html — extract.
18. telemetry 1.4.2 (Erlang). The module's docs and the README. https://telemetry.hexdocs.pm/telemetry.html — extract.
19. JDK 21. The Javadoc of `jdk.jfr.Event`.
    https://docs.oracle.com/en/java/javase/21/docs/api/jdk.jfr/jdk/jfr/Event.html — extract.
20. Go. Package runtime/trace. https://pkg.go.dev/runtime/trace — extract.
21. contra-tracer 0.2.1.1 (Haskell). Control.Tracer.
    https://hackage-content.haskell.org/package/contra-tracer-0.2.1.1/docs/Control-Tracer.html — extract.
22. Python. PEP 578, Python Runtime Audit Hooks. https://peps.python.org/pep-0578/ — extract.
23. Trio. Low-level API, Instrument API. https://trio.readthedocs.io/en/stable/reference-lowlevel.html — extract.
24. OpenTelemetry. Specification: Trace API; Error handling. https://opentelemetry.io/docs/specs/otel/trace/api/ —
    extract.
25. tracing 0.1.44 (Rust). The crate's documentation. https://docs.rs/tracing/latest/tracing/ — extract.
26. Celery. `Task.send_event`; the monitoring guide. https://docs.celeryq.dev/en/stable/userguide/monitoring.html —
    extract.
27. Prefect. Events. https://docs.prefect.io/v3/concepts/events — extract.
28. Textual. Guide "Events and Messages", the source of `@on`, the changelog.
    https://textual.textualize.io/guide/events/ — extract.
29. Django. Signals (5.2). https://docs.djangoproject.com/en/5.2/topics/signals/ — extract.
30. blinker, SQLAlchemy 2.0 "Events", structlog's typing module. https://docs.sqlalchemy.org/en/20/core/event.html — the
    signatures, extract.
31. Eliot. Message and action types. https://eliot.readthedocs.io/en/stable/generating/types.html — extract.
32. Python. PEP 634 (class patterns) and PEP 696 (defaults for type parameters). https://peps.python.org/pep-0696/ —
    sections, extract.
33. mypy. Issue 14833. 2023, open. https://github.com/python/mypy/issues/14833 — full.
34. pyright. Discussion 11244. 2026. https://github.com/microsoft/pyright/discussions/11244 — full; no maintainer's
    answer.
35. .NET runtime. DiagnosticSource User's Guide.
    https://raw.githubusercontent.com/dotnet/runtime/main/src/libraries/System.Diagnostics.DiagnosticSource/src/DiagnosticSourceUsersGuide.md
    — extract.
36. Go. Package log/slog. https://pkg.go.dev/log/slog — the overview, extract.
37. Rust RFC 2008, `non_exhaustive`. 2017. https://rust-lang.github.io/rfcs/2008-non-exhaustive.html — Motivation,
    extract.
38. Python 3.14. pickle. https://docs.python.org/3.14/library/pickle.html — extract.
39. CPython 3.14.8. The source of asyncio's threads and futures, of the thread and process executors, of threading, of
    logging's handlers and of multiprocessing's queues, read with `inspect.getsource` — the functions named, full.
40. CPython. Issue 78195, "loop.run_in_executor should propagate current contextvars".
    https://github.com/python/cpython/issues/78195 — full.
41. dask/distributed. The source of the client, worker, scheduler, broker and batched sends; issues 5552, 7471, 8704,
    7013, 8688. https://github.com/dask/distributed/tree/main/distributed — the code read; of the issues the bodies.
42. Python. logging.handlers; the logging cookbook. https://docs.python.org/3/howto/logging-cookbook.html — extract.
43. tqdm, joblib, mpire. The source of their worker communication. https://github.com/sybrenjansen/mpire — the code
    read; mpire's sentence on overhead from its docs, extract.
44. Ray. Configuring logging; application metrics.
    https://docs.ray.io/en/latest/ray-observability/user-guides/configure-logging.html — extract.
45. OpenTelemetry for Python. The threading instrumentation and the API's span module.
    https://github.com/open-telemetry/opentelemetry-python-contrib — the code read.
