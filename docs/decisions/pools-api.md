# Pools API

`Pools` is async only and opened by `async with Pools.open(cpu_workers=..., io_workers=..., cpu_backend=...)`, because
the close of a sync block would block the event loop. The interface for implementers of backends is in `strom.backends`,
apart from `__all__`.

Decided with it:

- `Pools.open` is keyword-only and checks its configuration at the call, so that the warning names the caller's line. It
  is short for `Pools.open_on(cpu=..., io=...)` with backend configs (user guide, Backends). Only these two construct a
  `Pools`, and pool sizes default to the hardware's.
- A backend config is a frozen dataclass whose `__call__` creates the backend on first use, so `PoolConfig` needs no
  protocol and `io=Processes(...)` is a type error.
- The GIL warning comes only for the literal `cpu_backend="thread"`: an explicit `Threads` for cpu is the user's choice.
- Names: the pool is the role, the backend what runs it. `open_on` is the block of `open` on the given backends.
  `CpuBackendKind` is a public alias, so that callers can type their backend parameter.
- A `Pools` shows only `open`, `open_on`, `config` and `closed`; a run reaches its backends through `backends_of(pools)`
  (`ARCHITECTURE.md`, Concurrency and pools).
- The interface is split: `Backend` has `run(fn, arg)` and `aclose`, so an implementer for "cpu" writes two methods;
  `StreamingBackend` adds what only `io_stage` needs, `affinity` and `release`.
- A backend knows nothing of runs: `run` gives fn(arg) or raises what it raised, and what a run adds to a pool task
  wraps the function it passes (`docs/decisions/offloading.md`).
- `strom.testing.check_backend` and `check_streaming_backend` check what a caller can observe of the contract
  (picklable, for other processes and hosts).
- The threads of `Threads` are named "threads" by default, those of `Pools.open` "cpu" and "io".

**Measured**, an `InterpreterPoolExecutor` behind `FromExecutor` against the built-in backends (2026-11-13; 4 workers,
medians)

| With the GIL | Interpreters | `Processes` | `Threads` |
| -- | -- | -- | -- |
| first call of fresh pools, ms | 134 | 3.4 | 0.3 |
| a cheap function, µs per item | 160 | 149 | 55 |
| CPU-bound items per second | 327 | 298 | 56 |

| Free-threaded | Interpreters | `Processes` | `Threads` |
| -- | -- | -- | -- |
| first call of fresh pools, ms | 167 | 9.3 | 0.4 |
| a cheap function, µs per item | 404 | 52 | 43 |
| CPU-bound items per second | 346 | 261 | 270 |

**Rejected**

- the run's failure flag as a keyword of `run` with a public `PoolTaskSkipped` (2026-11-05 to 2026-11-11: run policy in
  every transport; the thread backend set the flag that the contract said a backend never sets, so the same calls gave
  `PoolTaskSkipped` on threads and a result on processes; every implementer had to write the check to get it)
- `Pools.open` as an `@asynccontextmanager` itself (the config checked only on entry, the warning attributed to
  `contextlib`)
- `ExecutorSpec` injection (over-complication: it only re-exposed what `cpu_backend` chose; the backend interface
  instead removes the executor, which remote workers, interpreter pools and pinned iterators need)
- a `create()` method with a `BackendConfig` protocol (one more public name)
- an overload of `Pools.open` taking backends (two ways mixed in one call)
- a capability flag for the GIL warning (only the warning would read it)
- `Pools.backend()` and `Pools.close_later()` methods (public API that only the offloaders and tests needed)
- a private alias for `CpuBackendKind` plus `# type: ignore` in callers (an ignore in every caller that types its
  backend parameter)
- the name `Pool` (easy to confuse with `Pools`)
- the name `CpuBackend` (reads like a `Backend` subclass)
- the name `Pools.using` for `open_on` (until 2026-11-11: also the name of `using(handle, fn)`, an unrelated concept)
- the name `Pools.on` for `open_on` (says less: not that it is the block of `open`)
- the name `Pools.backed_by` for `open_on` (the glossary's word, but it reads as a property of pools that exist)
- the name `Pools.with_backends` for `open_on` (`async with Pools.with_…` stutters)
- an `Interpreters(workers=)` config for "cpu" (2026-11-13; `FromExecutor(factory=InterpreterPoolExecutor)` runs one):
  interpreters pay off only for CPU-bound work with the GIL, where `Processes` does about as well and starts 40× faster;
  free-threaded, `Threads` does it without either cost (Measured)
- backends as records of functions, or as Protocols in place of the two classes (`Run`, `PlacedRun`, `release`,
  `aclose`): four public names for two, and an implementer's class would lose the `@override` check against a base and
  the default of `close_handle`
