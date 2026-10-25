# Design review – strom (2026-11-10)

Scope: the complete code base, through the lenses of `ARCHITECTURE.md` (Hickey's simplicity, Elliott's denotational
design, parse don't validate, the Haskell stream libraries); focus on the overall design, the abstractions and the
process, with the sections of `docs/decisions.md` re-examined. `make check` was green at the start.

IDs: a letter per group and a number, most important first within a group; options get a lowercase letter (`A1a`).
"Confirmed" means a probe or an injected bug was run (the scripts are in `.checks/probes/`); everything else is from
reading. Measurements are of 2026-11-10 on a machine that was not idle. Delete this file once its findings are done or
rejected (rejections with their reason go to `docs/decisions.md`). Open: M1.

## A. Architecture and abstractions

### A1 to A5: implemented (2026-11-11)

- **A1a**: the thread and the process backend run on a pool with addressable workers (`strom._runtime.pinning_pool`); a
  process worker is a pool thread that forwards its calls to a child process. An `io_stage` iterator stays on its
  thread, releases and handle closes are calls pinned to every worker, and the `SIGUSR1` protocol is gone.
- **A2a**: the failure flag left the backend contract: `Backend.run(fn, arg)`; the run guards its pool tasks itself
  (`strom._interpreters.offloaders`: `FailureFlag`, `PoolTaskSkipped`, `_guarded`).
- **A3**: the reference semantics evaluates a leaf itself; `offloaders` is a module of `_interpreters`, and `Offloader`
  its one class.
- **A4**: `Focused.with_focus` (`strom._stages.model`); a lifting has one arm for every kind that holds a focus.
- **A5**: an `io_stage` function's list or tuple comes whole in one pool task (`open_iterator`), also through `using`.

The decisions are recorded in `docs/decisions.md` (Worker pool, Pools API, Offloading, Reference semantics, Lifting,
`io_stage` items, Worker handles, Module structure).

## C. Correctness

### C1 and C2: implemented (2026-11-11)

- **C1**: after a failure, a consumer that waits for an output waits until the block of `stream` has been left
  (`strom._runners`): one inside the block is cancelled meanwhile, at any depth of task groups, and the block raises the
  run's error alone; one outside gets its `RuntimeError` then (`docs/decisions.md`, Runners).
- **C2a**: the docstrings of `gather`, `bag` and `check_against_reference` say that the list of a `gather` is compared
  as one item and how a following stage sorts it (`docs/decisions.md`, Test tools for users).

## T. Tests

### T1: implemented with A4 (2026-11-11)

`test_lifting_keeps_every_setting` (`tests/stages/test_lifting.py`): the settings the repr shows are the same before and
after each lifting; it catches the four injected bugs.

## P. Process and docs

### P1 to P7: implemented (2026-11-11)

- **P1**: `docs/research/` is tracked, and `bin/check_docs.py` accepts a cited path only if it is tracked
  (`docs/decisions.md`, Docs check).
- **P2**: a measurement names its baseline by a tag, `baseline/2026-11-11` being the first (`.claude/rules/tests.md`,
  Benchmarks). The three baselines of the squashed history were not kept: the docs name those states in words and by
  date (`docs/decisions.md`, Benchmarks).
- **P3a**: the Makefile is the one definition of the checks; the tox envs and the git hooks run its targets, and a
  pre-push hook runs `make check`. The nix lines and the mode `--direct` of `bin/run_examples.py` are gone
  (`docs/decisions.md`, Checks).
- **P4**: `docs/decisions.md` has a section per topic: the decision in a few sentences that point to the design note or
  docstring, one bullet per rejected alternative (`.claude/rules/docs.md`).
- **P5**: the research notes carry no state of work; what they left open was done with A1 and A2 or is recorded as
  rejected (`docs/decisions.md`, Pools API and Agent docs).
- **P6**: a false positive of one checker gets that checker's ignore comment, and an unused one fails the check
  (`docs/decisions.md`, Checker false positives; `.claude/rules/typing.md`). `_make_step` and `next_item` have the
  shapes mypy and pyright accept.
- **P7**: the edit hook leaves a file outside the repository as it is (`docs/decisions.md`, Change checks).

## M. Smaller points

### M1. `using` names two concepts

- **Problem**: `Pools.using(cpu=..., io=...)` and `using(handle, fn)` are unrelated (one term per concept), and `Using`
  is public only as a return type.
- **Options**
  - **M1a**: rename the class method, and let `using` return a plain `Callable`, so that `Using` leaves `__all__`.
    Suggested name (2026-11-11): `Pools.open_on(cpu=..., io=...)`, the same block as `Pools.open`, on the given
    backends; shorter but less telling: `Pools.on`; with the glossary's word: `Pools.backed_by`. Not `Pools.of` (the
    name of the rejected sync variant) and not `Pools.with_backends` (`async with Pools.with_…` stutters).
  - **M1b**: keep the names; only `Using` leaves `__all__`.

### M2 and M3: implemented (2026-11-11)

- **M2**: the 17 names of the metrics are public in `strom.metrics`, none of them at the top level any more
  (`docs/decisions.md`, Public modules).
- **M3**: every element of a run starts its tasks through `start_tasks` (`strom._interpreters.run_context`;
  `docs/decisions.md`, Tasks of an element).

## Re-examined without a finding

Stages as data in the initial encoding, one task loop with local recording checks, fusion as a pass, fail-fast with one
group, async only, no sinks or sources, privacy by namespace.
