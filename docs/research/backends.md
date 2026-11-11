# Compositional backends – strom

Research of 2026-11-08: how the backend (`strom.backends`, `strom._runtime.executor_backend`) could be built from small
composable parts instead of class hierarchies, compared with how other systems compose execution, routing and the
lifetime of remote state. It describes the code of that date. Additions to the public API need the user's go-ahead;
decisions taken from this go to `docs/decisions/` (`pools-api.md`, `pools-lifecycle.md`, `worker-pool.md`,
`offloading.md`, `worker-handles.md`). Claims not checked against their sources are marked [unverified].

## Where strom stands

A backend today is one object holding five concerns, split over two class hierarchies:

| Concern | Where it lives now |
| -- | -- |
| running fn(arg) on some worker (transport) | `Backend.run`; `ExecutorBackend._submitted` |
| placement on a given worker | `affinity` keyword of `StreamingBackend.run`; ignored by `ThreadBackend` |
| skipping pool tasks after a failure | `failed` keyword of every `run`; `_guarded` (threads), pre-dispatch (`PicklingBackend`), ignored (processes) |
| releasing objects left in workers | `close_unreceived` (cancelled open), `close_later` (early stop), `_queued_closes` (at `aclose`), `close_handle` (worker handles) |
| measuring | not in the backend: the subclass `MeasuredPooled(Pooled)`, with `affinity_of` in `Pooled._run_io` for it |

The concerns are combined by inheritance and keyword arguments: `ExecutorBackend` carries `ThreadBackend`'s release
machinery, `ProcessBackend` overrides four of its methods, `ThreadBackend` is a diamond over `Backend`, and
`StreamingBackend.run` has four call shapes, of which `io_stage` uses three. Spelling the same operations as Protocols,
or as separate methods, only renames this: the concerns stay fused in one object.

Two facts about the code matter for any redesign:

- **Releases happen only at a run's end.** A step stops consuming early only when its run fails or is cancelled
  (`strom._interpreters.steps`: "stopped early (also cancelled)", "cancelled: the run failed elsewhere"), and that is
  also the only time a caller is cancelled while its pool task runs. So all three iterator release paths fire when the
  run ends, for a reason the backend never needs to know.
- **Worker handles already solve a scoped release.** `close_handle(key)` closes one key's objects in every worker
  process after the calls in flight there, and later opens of that key are refused (decisions row Worker handles). That
  is a release of a *scope*, with the hard parts (waking idle workers, waiting for calls in flight, refusing late opens)
  solved for processes.

## How other systems compose this

- **Finagle, "Your Server as a Function"** (Eriksen, 2013): a *service* is a function `Req => Future[Rep]`, a *filter*
  wraps one (`(Req, Service) => Future[Rep]`), and `andThen` composes them. Timeouts, retries and authentication are
  filters, independent of the service they wrap ([paper](https://www.academia.edu/73677852/Your_server_as_a_function),
  [QCon 2014 slides](https://qconsf.com/sf2014/system/files/presentation-slides/marius%20eriksen%20qcon%20sf%2014.pdf)).
  Rust's tower does the same with `Service` and `Layer`
  ([tower `Service`](https://docs.rs/tower/latest/tower/trait.Service.html)).
- **Akka routers**: routing is a separate piece (`RoutingLogic`) over a set of routees; a consistent-hashing router
  sends every message with the same key to the same routee, keyed by a mapping function or by an envelope the sender
  adds
  ([ConsistentHashingRoutingLogic](https://doc.akka.io/japi/akka-core/2.9/akka/routing/ConsistentHashingRoutingLogic.html)).
  Affinity is routing by key, not a property of the workers.
- **Dask, Ray**: placement as request data (`workers=` and `allow_other_workers=`;
  `NodeAffinitySchedulingStrategy(node_id, soft=)`), soft or hard
  ([Dask locality](https://distributed.dask.org/en/stable/locality.html),
  [Ray scheduling](https://docs.ray.io/en/latest/ray-core/scheduling/index.html)).
- **Ray ownership** (Wang et al., NSDI 2021): each remote object has an owner, the process that created it, and the
  owner coordinates its lifetime; objects are freed by distributed reference counting once all references are gone
  ([paper](https://www.usenix.org/conference/nsdi21/presentation/cheng),
  [Ray objects](https://docs.ray.io/en/latest/ray-core/objects.html)). Release is tied to an owner, not to each call.
  strom rejected reference counting for unreceived results (decisions row Offloading).
- **Regions** (Tofte and Talpin): values are allocated into regions whose lifetime is a lexical scope (`letregion`), and
  a region is freed as a whole; there is no per-object free
  ([Aiken et al. 1995, on the Tofte–Talpin baseline](https://www2.eecs.berkeley.edu/Pubs/TechRpts/1995/5202.html)).
- **Structured concurrency** (Smith, 2018): a nursery doesn't end until its tasks have finished, so lifetimes nest
  lexically
  ([Notes on structured concurrency](https://vorpus.org/blog/notes-on-structured-concurrency-or-go-statement-considered-harmful/)).
  strom's runs and `worker_handle` blocks already nest this way.
- **Records of functions** (the Handle pattern, Van der Jeugt 2018): a service is a value built from a config;
  implementations, wrappers and test doubles are values
  ([Handle pattern](https://jaspervdj.be/posts/2018-03-08-handle-pattern.html)).
- **Pool checkout** (Erlang poolboy): a caller borrows a worker exclusively, uses it, and returns it; a checkout model,
  not a routing model ([Elixir Forum](https://forum.elixirforum.com/t/poolboy-vs-dynamicsupervisor/13924)). Pinning an
  iterator to a worker for its lifetime would be a checkout, and holding a worker between items is what `io_stage`
  avoids (`Offloader.streamed`).

## Approaches

### 1. Layers: cross-cutting behaviour as `Run -> Run` (Finagle filters)

A backend's core is a polymorphic function, and every concern that wraps a call is a layer around it:

```python
class Run(Protocol):
    async def __call__[A, B](self, fn: Callable[[A], B], arg: A) -> B: ...


measured(skipping(threads.run, failed), recorder, step_id)  # a run's stack, per step occurrence
```

- **Layers:**
  - `skipping(failed)` replaces the `failed` keyword: a pre-dispatch check for any transport.
  - `measured` replaces `MeasuredPooled` and moves `_timed` worker-side through the layer.
  - `pickling` makes a test transport of any transport: `PicklingBackend` minus its routing.
  - `in_process` wraps the calls of process workers that use worker handles.
- **The off case:** when recording is off, the layer is absent, so it costs nothing (no `if recording` per pool task).
  That holds by construction rather than by the subclass choice in `step_offloader`.
- **Where knowledge lives:** a transport-specific layer, such as the in-worker failure check that only threads can do
  (shared memory), is applied by that transport's config. The rejected `shares_memory` flag is not needed: the config
  knows (decisions row Offloading).
- **Probe** (2026-11-08, a probe script, mypy strict with `--disallow-any-expr`, pyright 1.1.414, ty 0.0.91):
  - Typing works: layers written as frozen dataclasses with a generic `__call__`, or as closures returning a nested
    generic `def`, keep the call generic through a three-layer stack, and the results stay `int` and `str` in all three
    checkers.
  - A layer may change the worker-side function's result type and unwrap it (`Timed[B]` back to `B`).
  - mypy and pyright reject a non-generic implementation of `Run`; **ty accepts it**, so ty alone doesn't guard
    implementers.
- **Cost:** one Python frame and coroutine per layer per pool task on the event loop \[unmeasured; `bin/ab.py` before
  adopting\].

### 2. Scopes: one release for everything left in workers (regions)

Objects that live in workers (`io_stage` iterators and worker handles) belong to a *scope*: the run that opened them, or
the `worker_handle` block. A scope ends lexically (the run's end, the block's end), and the backend gets one operation
for it:

```python
async def release(self, scope: ScopeId) -> None: ...
```

It releases every object of `scope` on every worker holding some, after that scope's calls in flight there, and refuses
that scope's later calls. This is `close_handle`'s contract with "key" generalized to "scope". The worker-side
registries (`strom._runtime.iterator_registry`) tag entries by scope, and `open_iterator` registers under the scope it
is called with.

- **What it replaces:**

  - `close_unreceived` and the release done-callbacks (`ExecutorBackend._close_unreceived`, `_close_on` in
    `tests/helpers.py`);
  - `close_later` and `_queued_closes`;
  - `MeasuredPooled`'s recorder-error release and `affinity_of`;
  - `close_handle` (now the same operation).

  An unreceived result is released whatever the reason it went unreceived, because releasing doesn't depend on receipt.
  This is not the rejected "flag the pool thread checks after opening" (it races with receipt) and not reference
  counting.

- **Timing:** releases today happen only at a run's end anyway (see above), so a scope releases no later than now. If a
  future combinator stops consuming mid-run (e.g. a `take`), it closes that iterator promptly with an ordinary pinned
  call, and the scope remains the safety net.

- **Pools lifecycle:** `release` must not wait behind a pool task that only the shutdown frees (decisions row Pools
  lifecycle, the rejected facade that awaited closes). So the run's end starts the release without awaiting it, and
  `aclose` runs the releases still pending: the backend keeps one queue of scope releases instead of three release
  paths.

- **Process workers:** use the existing `SIGUSR1` machinery (`process_pool_handles`) for any scope, not only handle
  keys. Remote backends implement one broadcast instead of four operations.

- **The failure flag** is per run, as the scope is: `skipping` (approach 1) can take it from the scope, and a transport
  that checks in the worker gets the scope with each call.

- **Open question:** does a scope per *run* hold iterators too long when a run is long and many inputs are cancelled
  mid-run? By the fact above this doesn't happen today. It would need a probe if mid-run stops are added.

### 3. Routing as data, not as a backend kind (Akka routers)

Placement becomes request data, `at: WorkerId | None`, handled by the transport's dispatcher, as in Dask, Ray and Akka.
The streaming capability then is "a transport that accepts `at`":

```python
class PlacedRun(Protocol):
    async def __call__[A, B](self, fn: Callable[[A], B], arg: A, at: WorkerId | None) -> B: ...


def anywhere(run: PlacedRun) -> Run: ...  # every placed transport is also a plain one
```

- **The cpu/io split:** it is the difference between `Run` and `PlacedRun`, with an adapter from one to the other, not a
  subclass with an overridden method.
- **Pitfall, routing over independent workers:** a router over per-worker queues pushes unplaced calls to a worker ahead
  of time, so a call waits behind a long one while another worker idles (rejected in the plan for pinned threads for one
  executor per thread; Akka's routers push the same way [unverified]). For threads, placement is a dispatcher with a
  shared queue plus one queue per worker (`_PinningPool` of the pinned-threads plan), not a router composed over opaque
  workers. For remote hosts, where each host has its own queue anyway, a router over per-host transports composes
  cleanly.
- **Placement stays hard:** `LookupError` for a lost worker, like Ray's `soft=False`.

### 4. A backend as a record of its parts (the Handle pattern)

What a backend config creates is then a small record, not a class to subclass:

```python
@dataclass(frozen=True)
class Pool:  # "cpu"
    run: Run
    release: Callable[[ScopeId], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]]


@dataclass(frozen=True)
class PlacedPool:  # "io"
    run: PlacedRun
    release: Callable[[ScopeId], Awaitable[None]]
    aclose: Callable[[], Awaitable[None]]
```

- **Built-ins:** each is a function from its config to a record, built from parts:

  - `_Executors`: lazy creation, replacing a broken executor, retiring a full one, shutdown;
  - the pinning dispatcher (threads);
  - `Holders` (processes);
  - the worker-side wrappers.

  No `ExecutorBackend` base: the three built-ins share parts, not a superclass.

- **Probe** (2026-11-08, a probe script, the same checkers): a dataclass field typed by a callable Protocol with a
  generic `__call__` accepts a bound generic method and rejects a wrong one, in all three checkers.

- **Cost:** the record types and `Run`/`PlacedRun` are public names that implementers need. That's four names for
  `Backend`/`StreamingBackend`'s two (decisions: "one more public name" rejections). A class with `__call__`, `release`
  and `aclose` that satisfies a Protocol works as well; whether the record is a dataclass or a Protocol is secondary to
  approaches 1–3.

### 5. Effect handlers, for the theory

The offloader's operations (run anywhere, run at, release scope) are the operations of an algebraic effect, and a
backend is its handler. Layers are handlers that forward to an outer one, and composing them is composing handlers
(Plotkin and Pretnar, "Handlers of algebraic effects", 2009 [unverified]). Python has no effect handlers; asyncio plus
approach 1 is their practical encoding. The view justifies the design: every layer is a natural transformation between
interpretations of the same operations, so a stack of layers satisfies the same contract as its transport, and
`check_backend` can check the composed stack.

## Recommendation

Approaches 1–3 together; approach 4 only as far as it needs no extra public names. In order, each step leaving
`make check` green:

1. **Scopes** (approach 2), internal first: the registries tag entries by run, the run's end releases its scope, and
   `close_unreceived`, the release done-callbacks and `MeasuredPooled`'s release go away. This is the largest
   simplification, and it is testable against today's tests of closing (`test_offloading`, `test_backends`, the registry
   fixture).
2. **Layers** (approach 1) for measuring and skipping: `MeasuredPooled` and the `failed` keyword go, the offloader is
   one class over a `Run` stack; `bin/ab.py` on the io and cpu rows.
3. **Built-ins from parts** (approach 4's internals), together with `_PinningPool` from the plan for pinned threads
   (approach 3's dispatcher).
4. **The public interface** last, when its shape has settled: a transport is `Run` or `PlacedRun` plus `release` and
   `aclose`; `close_handle`, `close_later` and `close_unreceived` disappear from `strom.backends`.

Steps 1–3 are internal; step 4 changes `strom.backends` and needs the user's go-ahead. A plan goes to `docs/plans/`.
