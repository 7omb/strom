# Fix: the cost of handling one input in an event-loop step

Status 2026-11-05: proposal (option (b) of the migration; the regression is accepted until then).

## Problem

Since runs take their inputs one by one (2026-11-05: `collect(stage, inputs)`, now `stream`), a run whose first step is
an event-loop step costs about twice as much per input as before, when a source made all items inside one fused group
(`bin/ab.py` against that state, which no longer exists; 9 interleaved runs each, us_per_input, 2026-11-05):

| Row | with a source | with inputs | ratio |
| -- | -- | -- | -- |
| identity only | 2.79 | 5.50 | 1.97 |
| 1 / 3 / 6 event-loop steps | 2.96 / 4.49 / 5.83 | 5.70 / 9.64 / 11.04 | 1.92 / 2.15 / 1.89 |
| first(stage) | 3.76 | 5.75 | 1.53 |
| async_stage, io_stage, product(stage, stage) |  |  | 0.98 – 1.05 |

The same stage on 50,000 inputs against one input whose first step makes the 50,000 items: 5.55 against 2.97 us per item
(`identity()`), 8.83 against 3.09 (`identity() | stage(neg)`). So the cost is per handled input of an event-loop step,
not the runner or its consumer. Every event-loop step that receives items from a queue pays it, also one after an
`io_stage`.

Where it goes (microbenchmark, 200,000 inputs): an async generator per input as `_expanding` and `_fair` build it,
iterated with `async for`, 1.80 us; iterating `fn(item)` directly, 0.18 us; a `get_nowait` from the input queue, 0.21
us. The async generator is about 1.6 of the 2.5 us.

## Proposal

Event-loop steps get a sync ItemFn, and the task loop iterates it without an async generator.

1. `item_fns.py`: `type _SyncItemFn[A, B] = Callable[[A], Iterator[B]]` and a builder for a step whose leaf is
   `Expand(resource=None)`: `lambda item: iter(fn(item))`. Its iterator is closed by the task loop (below), as
   `_expanding` closes it now.
2. Fusion: a group's leaf stays `AsyncExpand` for the reference semantics and for kinds that use ItemFns, but the group
   also keeps its sync function with SKIPs (`group_fn` of `_fair`). Simplest carrier: a private leaf kind
   `Expand(resource=None)` whose function may emit `_Skip.SKIP`, used only by `fused`; `item_fn_of` turns it into
   `_fair(...)` where an ItemFn is needed, the step loop iterates it directly. (The leaf kinds are a closed union: every
   `match` on `Leaf` names the kind; the checkers flag a missing arm.)
3. `steps.py`, `_run_step_tasks`: two inner loops in the one task loop, chosen once per step occurrence (as `recording`
   is):
   - sync: `iterator = sync_item_fn(a)`, `for b in iterator:` with the same puts (`put_nowait` when the queue has room,
     else `await outq.put`), counting SKIPs and `await asyncio.sleep(0)` after every `_SKIP_BUDGET` of them (the
     fairness `_fair` gives now); close the iterator in `finally` when it stops early (`close_if_closable`), as now;
   - async: the current `async for b in outs` path, for all other leaves. The rest of the loop (input, focus
     `split`/`merge`/`finish`, recording, failures) stays one code path.
4. Branch and lifted steps go through `FocusedStep` with the same loop: they gain too.

Expected: about 1.6 us less per input of an event-loop step or group, i.e. the rows above back to within about 1 us of
their numbers with a source; to be measured, not assumed.

## Why this and not the alternatives

- An internal source-like step in the runner (option (a)) fixes only the first step of a run, and puts its name into
  group names and stage notes.
- Separate task loops per leaf kind were rejected before (docs/decisions.md, Metrics check: duplicated code); this keeps
  one loop with one branch at the iteration, like the `recording` checks.

## Risks and checks

- Closing: a sync iterator stopped early (failure, cancellation, a full queue then cancelled) must be closed in the
  task's `finally`; the closing tests in `tests/interpreters/test_item_fns.py` and `test_fusion.py` cover it (keep
  references, check inside the loop: `.claude/rules/tests.md`).
- Fairness: `test_runs_never_freeze_the_event_loop` (all stretches, incl. "inputs dropped") must pass unchanged.
- Fusion keeps the meaning: `test_fusion_keeps_the_meaning`, and the reference semantics is untouched.
- Typing: the private leaf kind with SKIPs needs one cast at most (fusion already holds the library's only casts); no
  `Any`.

## Steps

1. Reproduce in the current tree (the state with a source is gone, so the table cannot be measured again): the same
   stage on 50,000 inputs against one input whose first step makes the 50,000 items, and the microbenchmark of an async
   generator per input, saved with the date.
2. Implement 1–3; `make check`; `bin/typing_snapshot.py diff --against HEAD`.
3. Injected bugs (`bin/mutant.py`): no close of the sync iterator when stopped early; no `sleep(0)` after the SKIP
   budget; the sync path chosen for an io leaf.
4. `bin/ab.py HEAD .` on `benchmarks/benchmark.py -k "event_loop or lifted or product"`, and the comparison of step 1
   again (many inputs should then cost about what one input's items cost); record the numbers in docs/decisions.md
   (sections "Fusion" and "Runner costs"), then delete this plan.
