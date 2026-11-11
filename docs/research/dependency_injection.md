# Dependency injection instead of inheritance in `_runtime` – strom

Research of 2026-11-09: where `strom._runtime` shares code by inheritance, what dependency injection (DI) and
domain-driven design (DDD) recommend for such code, and designs that inject parts instead. It complements
`docs/research/backends.md`, which composes backends from layers, scopes and records (its approaches are cited here, not
repeated). It describes the code of that date. Additions to the public API need the user's go-ahead, and decisions taken
from this go to `docs/decisions/` (`pools-api.md`, `offloading.md`, `module-structure.md`, `worker-pool.md`). Claims not
checked against their sources are marked [unverified]. Designs are unprobed unless they say so.

## Where `_runtime` inherits

| Hierarchy | Kind | What a subclass gets or overrides |
| -- | -- | -- |
| `Backend` \<- `StreamingBackend` | interface (public, `strom.backends`) | abstract `run`, `aclose`; `close_handle` with a do-nothing default; `close_later` |
| `ExecutorBackend` \<- `ThreadBackend`, `ProcessBackend` | implementation, to share code | everything below |
| `ThreadBackend(ExecutorBackend, StreamingBackend)` | a diamond over `Backend` | the contract from one base, the code from the other |
| `Offloader` \<- `Pooled` \<- `MeasuredPooled` | interface, then implementation | `MeasuredPooled` overrides `_run_cpu`/`_run_io` and calls `super()` |

Interface inheritance (`Backend`, `Offloader`) is the port that implementers and the interpreters see. It is not the
problem. Implementation inheritance is, in three places:

- **`ExecutorBackend` holds four concerns.** Its subclasses use them through protected members:

  1. *the executor's lifetime*: created lazily by `factory`, dropped when broken, never created after `aclose`
     (`_current`, `_executor`, `_discard`, `_closed`);
  2. *submitting*: `_submitted` (submit, `wrap_future`, catch `BrokenExecutor`);
  3. *releasing results left in workers*: `_close_unreceived`, `_submit_close`, `_queued_closes`, `_close_done`, and
     running them in `_shut_down`;
  4. *shutdown*: `aclose`, and the `cancel_futures` fallback in `_shut_down`.

  Concern 3 serves only `ThreadBackend`, the one streaming subclass. `ProcessBackend` and `FromExecutor` are "cpu" only
  and never call `close_later` or pass `close_unreceived`, yet each instance carries that code. This is the inheritance
  form of what the module layout rule forbids for modules (`ARCHITECTURE.md`, Packages, "Module layout": what only one
  feature needs belongs to that feature).

- **`ProcessBackend` reaches into its base's state.** `_retire` reads and clears `self._current`. `_discard` and
  `aclose` extend the base through `super()`, `_new_executor` is passed to `super().__init__` before `self._handles`
  exists (safe only because the factory is called lazily), and `run` must call `_submitted`. A change to the base's
  invariants (for example when `_current` may be None) breaks the subclass silently: the fragile base class.

- **`MeasuredPooled` is a decorator written as a subclass.** It changes the calls of `Pooled`, not its algorithm, and
  `Pooled._run_io` takes `affinity_of` only for it (`docs/research/backends.md`, approach 1).

## What the literature recommends

**Composition and DI**

- **Favour composition over inheritance, and keep inheritance for interfaces.** The Gang of Four's second principle.
  Brandon Rhodes shows the Python forms: adapter, decorator and bridge instead of a subclass per combination
  ([python-patterns.guide](https://python-patterns.guide/gang-of-four/composition-over-inheritance/)). Hynek Schlawack
  distinguishes three kinds of subclassing: abstract data types (interfaces) are fine, specialization is rarely fine,
  and code sharing is the harmful one, replaced by composition
  ([Subclassing in Python Redux](https://hynek.me/articles/python-subclassing-redux/)). `ExecutorBackend` is code
  sharing.
- **Template method versus strategy.** A base class calling hooks that subclasses override is the template method;
  passing the varying part in is the strategy. `ExecutorBackend` is a template method whose hooks (`_discard`,
  `_new_executor`) do not appear in its docstring, so they form an implicit protected API.
- **Constructor injection and a composition root.** Dependencies come in through the constructor and are assembled in
  one place near the entry point
  ([Fowler, "Inversion of Control Containers and the Dependency Injection pattern"](https://martinfowler.com/articles/injection.html);
  [Seemann, "Composition Root"](https://blog.ploeh.dk/2011/07/28/CompositionRoot/)). In strom each backend config's
  `__call__` (`Threads`, `Processes`, `FromExecutor`) is already that root, run once per `Pools` on first use.
  `Pools.open_on` is the root of the whole runtime.
- **Inject volatile dependencies only.** Seemann and van Deursen ("Dependency Injection Principles, Practices, and
  Patterns", 2019, ch. 1 [unverified]) inject what varies, needs a test double or is nondeterministic: an executor, an
  OS process. A stable internal helper (a dict, a small state holder) is constructed inside. Injecting everything gives
  the "constructor over-injection" smell.
- **No container or service locator in a library.** A DI-friendly library takes its dependencies as arguments and leaves
  composition to its caller ([Seemann, "DI-Friendly Library"](https://blog.ploeh.dk/2014/05/19/di-friendly-library/);
  [Service Locator is an Anti-Pattern](https://blog.ploeh.dk/2010/02/03/ServiceLocatorisanAnti-Pattern/)). Python
  practice agrees: "Architecture Patterns with Python" assembles its handlers in a hand-written `bootstrap` function,
  with no framework ([cosmicpython, ch. 13](https://www.cosmicpython.com/book/chapter_13_dependency_injection.html)).
- **Ambient context is an anti-pattern, except where calls cannot carry the dependency** (Seemann and van Deursen
  [unverified]). strom's worker side is that case: a pickled top-level function cannot receive the worker's handle table
  or iterator registry, so an initializer (`init_handles`, `init_worker`, `init_process`) installs them as per-process
  or per-thread state. That initializer is the worker's composition root. DI stops at the process boundary.

**Precedents in the stdlib and in async libraries**

- `ProcessPoolExecutor(mp_context=, initializer=)` injects the start method and the worker setup.
- `loop.run_in_executor(executor, …)` takes the executor as an argument.
- Trio and anyio pass `limiter=` to `to_thread.run_sync`, an injected `CapacityLimiter`, instead of a subclass per
  limit.
- anyio's backends are classes implementing one interface (`AsyncBackend`), with no shared implementation base
  [unverified for 4.16.0].

**DDD, where it applies.** strom is a library, not a business domain, so DDD's tactical patterns (repositories, domain
events) mostly do not fit. Its strategic ideas do:

- **Ports and adapters** ([Cockburn, Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture/)).
  `Backend` and `StreamingBackend` are the port, and the built-in backends and `PicklingBackend` are adapters. An
  adapter should depend on the port and its own infrastructure, never on another adapter. `ThreadBackend` and
  `ProcessBackend` depend on the adapter `ExecutorBackend`.
- **Ubiquitous language.** Each part gets one name from `GLOSSARY.md`. The parts proposed below need entries.
- **Aggregates guard invariants.** `ProcessPoolHandles` already acts as one: an aggregate root over its per-executor
  `_ExecutorHandles`, which only it creates, discards and stops. The executor's lifetime (current, broken, retired,
  closed) is an entity with a state machine, implicit today in `_current` and `_closed`. Explicit states would follow
  the precedent of `HandleTable` (decisions row Worker handles).
- **Don't abstract before the second implementation.** Evans's supple design, and the rejection pattern of this repo:
  "one more public name", "options without a use".

## Designs

### D1. Final backends composed of shared parts (recommended)

There is no implementation base class. Each backend is a final class that implements the port directly and holds its
parts:

```python
@final
class ExecutorSlot[E: Executor]:
    """The current executor of a backend: created by `factory` on first use and after one broke or was
    retired, never after `close`."""

    def __init__(self, factory: Callable[[], E], on_broken: Callable[[E], None] = _ignore) -> None: ...
    async def run[A, B](
        self, fn: Callable[[A], B], arg: A, unreceived: Callable[[Future[B]], None] | None = None
    ) -> B: ...
    def current(self) -> E: ...  # created on first use; for queued closes
    def retire(self, executor: E) -> bool: ...  # False if it is no longer current
    def close(self) -> E | None: ...  # final; the executor for `shut_down`


def shut_down(executor: Executor) -> None: ...  # with the `cancel_futures` fallback
```

`run` submits, awaits the future, drops and shuts down a broken executor, then calls `on_broken`. It hands the future to
`unreceived` (in the event loop's thread) if the caller was cancelled. The backends are then:

| Backend | Parts | Its own code |
| -- | -- | -- |
| `ExecutorBackend` (`FromExecutor`) | `ExecutorSlot(factory)` | `run`, `aclose` (two lines each) |
| `ThreadBackend` | `ExecutorSlot(factory)`, a close queue | `_guarded`, the release of unreceived results, `close_later`, running queued closes at `aclose` |
| `ProcessBackend` | `ExecutorSlot(partial(handles.start, make), on_broken=handles.discard)`, `ProcessPoolHandles` | `in_process`, its retired list, `close_handle` as `handles.close_handle(key, full=self._retire)` |

- **Where code moves:** the release machinery (concern 3) moves from `executor_backend` to `thread_backend`, its only
  user. `ExecutorSlot` gets a module of its own (shared by three slices, named 1:1). The slices stop importing each
  other: `thread_backend` and `process_backend` import the slot module and the contract, not `executor_backend`. That is
  the adapter rule above.

- **What gets injected** (per the volatile-only rule):

  - the executor factory: it varies per config, and tests pass their own (`on_executor` in `tests/helpers.py`);
  - `on_broken`: process pools only.

  The slot, the close queue and `ProcessPoolHandles` are stable internals. Each backend constructs its own, as
  `ProcessBackend` constructs `ProcessPoolHandles` today. Constructors keep their signatures, so `on_executor` and the
  tests of `process_pool_handles` stay as they are.

- **What it fixes:**

  - The diamond goes: `ThreadBackend(StreamingBackend)`.
  - `ProcessBackend` no longer touches another class's `_current`.
  - The cpu-only backends no longer carry release code.
  - The slot's states can be made explicit (`_Unstarted`, `_Running(executor)`, `_Closed`, like `HandleTable`).

- **Fit with planned work:** the plan for pinned threads replaces the executor behind `ThreadBackend` with
  `_PinningPool` and drops `_queued_closes` for threads. Under D1 that touches `thread_backend` only. Under the current
  hierarchy it has to keep `ExecutorBackend`'s hooks working for an executor that routes by affinity. D1 is step 3 of
  `docs/research/backends.md`'s recommendation ("built-ins from parts") without its public changes.

- **Cost:**

  - The call depth per pool task stays the same: `backend.run` calls `slot.run` where it called `self._submitted`
    \[unmeasured: `bin/ab.py -- -k "thread_pool_io_stage or cpu_stage"`\].
  - One more module and one or two glossary terms.
  - `run` and `aclose` are written three times, two to four lines each. That is delegation, not duplicated logic.

- **Public API:** none. `ExecutorBackend` keeps its name and its constructor and is returned by `FromExecutor` as
  before. It is no longer a base class.

### D2. One configurable cpu backend with strategies

`ProcessBackend` and `ExecutorBackend` merge into one final `ExecutorBackend(slot, in_worker, teardown)`:

- `in_worker` wraps each call: `in_process`, or no wrapper for `FromExecutor`.
- `teardown` is a protocol (`start`, `discard`, `retire`, `close_handle`, `stop`), implemented by `ProcessPoolHandles`
  and by a null object for executors without handles.

`ThreadBackend` stays separate, because one class cannot be both `Backend` and `StreamingBackend` without making
`io=FromExecutor(...)` type-check (decisions row Pools API: `io=Processes(...)` is a type error).

- **For:** one fewer class.
- **Against:**
  - The teardown protocol has one real implementation and a null object. It is shaped by the process pool, so it is
    speculative generality: an `Interpreters` backend (`docs/todo.md`) can't use the `SIGUSR1` teardown, and remote
    backends implement `Backend` directly.
  - It puts back the coupling D1 removes: the configs choose among combinations of one class instead of composing parts.

Not recommended. Revisit it if a second backend needs the per-executor handle lifecycle.

### D3. Backends as records of functions (`docs/research/backends.md`, approaches 1 and 4)

A config builds a record of `run`, `release` and `aclose`. Layers (`skipping`, `measured`, `in_process`) are functions
from `Run` to `Run`, injected by the config. This is DI in the functional form (the Handle pattern). It goes further
than D1: it changes the public contract (`Run`, `PlacedRun`, scopes in place of `close_handle`, `close_later` and
`close_unreceived`), so it needs the user's go-ahead. D1's parts (`ExecutorSlot`, the close queue, `ProcessPoolHandles`)
are the parts D3 would assemble, so D1 is no detour on the way to D3.

### O1. The measuring offloader as an injected decorator

`Pooled` becomes final and takes its pool calls as a part:

```python
class PoolCalls(Protocol):   # private; the two operations `Pooled` uses
    async def cpu[A, B](self, fn: Callable[[A], B], arg: A) -> B: ...
    async def io[A, B](
        self, fn: Callable[[A], B], arg: A, close_unreceived: …, *, affinity: …, affinity_of: …
    ) -> B: ...

step_offloader(...) = Pooled(_BackendCalls(backends, failed))                       # unmeasured
                    | Pooled(_MeasuredCalls(_BackendCalls(backends, failed), recorder, step_id))
```

- **For:**
  - Measuring becomes a decorator that can be tested on its own.
  - `Pooled` no longer has protected hooks.
  - The unmeasured path still has no `if recording` check: the decorator is absent.
- **Against:**
  - `affinity_of` stays in the protocol for the decorator alone, until scopes remove it (`docs/research/backends.md`,
    approach 2).
  - It adds one private protocol.
  - A generic-method protocol is matched by all three checkers, but ty also accepts a non-generic implementation
    (`.claude/rules/typing.md`).
- **Cost:** the frame depth equals today's `super()` chain [unmeasured].
- **Verdict:** worth it together with D3's layers. On its own it moves the same code around.

### What stays inheritance

- `Backend`, `StreamingBackend` and `Offloader` are interfaces. A `Protocol` instead of the ABCs would make
  implementers' classes structural: no import of `strom.backends` needed, but no `@override` check against a base
  either. `close_handle` would lose its default, so every "cpu" implementer would write three methods instead of two
  (decisions row Pools API). Not recommended.
- The worker side (`iterator_registry`, `process_handles`) keeps its ambient per-worker state, installed by initializers
  (see above).

## Recommendation

1. **D1**, internal, one change: add `ExecutorSlot`, make the three backends final and composed, move the release
   machinery into `thread_backend`, and give the slot explicit states. Checks per skill `validate-change`: the suite,
   the typing diff, and `bin/ab.py` on the thread and process rows. Afterwards, record the decision in the Module
   structure row and remove the line "`ExecutorBackend`, the base of the others" from `ARCHITECTURE.md`. Best done
   before step 2 of the plan for pinned threads, which then changes `thread_backend` only.
2. **O1** only together with the layers of `docs/research/backends.md` (its steps 1–2), not on its own.
3. **D2** no; **D3** as `docs/research/backends.md` recommends, once its public shape has settled.
