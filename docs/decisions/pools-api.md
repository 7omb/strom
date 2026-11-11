# Pools API

Async only: `async with Pools.open(cpu_workers=..., io_workers=..., cpu_backend=...)`, keyword-only, its configuration
checked at the call (the warning names the caller's line), short for `Pools.open_on(cpu=..., io=...)` with backend
configs (user guide, Backends): frozen dataclasses whose `__call__` creates the backend on first use, so `PoolConfig`
needs no protocol and `io=Processes(...)` is a type error; only `Pools.open`/`Pools.open_on` construct a `Pools`; pool
sizes default to the hardware's (2026-11-06). The GIL warning only for the literal `cpu_backend="thread"` (an explicit
`Threads` for cpu is the user's choice). Names: the pool is the role, the backend what runs it; `open_on` (2026-11-11)
is the block of `open` on the given backends; public alias `CpuBackendKind` (callers type their backend parameter). A
`Pools` shows only `open`, `open_on`, `config` and `closed`; a run reaches its backends through `backends_of(pools)`
(see Concurrency and pools). The interface for implementers in `strom.backends`, apart from `__all__`, split
(2026-11-06) into `Backend` (`run(fn, arg)`, `aclose`: an implementer for "cpu" writes two methods) and
`StreamingBackend` (adds what only `io_stage` needs: `affinity`, `release`). A backend knows nothing of runs
(2026-11-11): `run` gives fn(arg) or raises what it raised, and what a run adds to a pool task wraps the function it
passes (see `offloading.md`). `strom.testing.check_backend`/`check_streaming_backend` check what a caller can observe of
the contract (picklable for other processes and hosts). `Threads` threads are named "threads" by default (`Pools.open`:
"cpu" and "io")

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
- the name `Pools.using` (until 2026-11-11: also the name of `using(handle, fn)`, an unrelated concept)
- in its place `Pools.on` (says less than `open_on`: not that it is the block of `open`)
- in its place `Pools.backed_by` (the glossary's word, but it reads as a property of pools that exist)
- in its place `Pools.with_backends` (`async with Pools.with_…` stutters)
- backends as records of functions, or as Protocols in place of the two classes (`Run`, `PlacedRun`, `release`,
  `aclose`: `docs/research/backends.md`, approach 4, and `docs/research/dependency_injection.md`, D3): four public names
  for two, and an implementer's class would lose the `@override` check against a base and the default of `close_handle`
