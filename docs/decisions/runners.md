# Runners

There is one runner, and it is async only, `async with stream(stage, inputs, pools) as outputs`, because a loop driven
from sync code costs 24 µs per resume. Its name pairs with `run_reference`.

Decided with it:

- A feeder (`_feed`) puts the inputs into the queue of the stage's first step, which `start_streaming` returns with the
  outputs (2026-11-05: the runner uses none of `streaming`'s internals).
- The inputs belong to the caller and are not closed. An error of the inputs ends the run like a step's (failure flag
  set), without a stage note.
- The outputs are a class (`_Outputs`): several consumers may share it, and one outside the block gets `RuntimeError`.
- After a failure, a consumer that waits for an output waits for the end of the block: one inside the block is cancelled
  meanwhile, however deep in task groups, and one outside gets its error then.
- Folds over a whole run are the consumer's code.
- The costs of the runner: `docs/decisions/runner-costs.md`.

**Measured**, `run_overhead_one_item` with the event that such a consumer waits on (`bin/ab.py`, `BENCH_SCALE=0.5`, 15
interleaved runs pinned to the P-cores, 2026-11-11)

| The event is made | Ratios | p |
| -- | -- | -- |
| per run | 1.012, 1.005 | 0.044, 0.007 |
| by the first consumer that waits | 0.998, 0.987 | 0.42, 0.31 |

**Rejected**

- a sync runner on a thread (it changes where event-loop functions run)
- an async generator as the outputs (no two consumers; PEP 789's hazard when iterated directly)
- a waiting consumer giving the block's cancellation one loop iteration before it takes itself for one outside the block
  (until 2026-11-11: the cancellation takes an iteration per task group around the consumer, so from three groups on the
  consumer raised the `RuntimeError`, which the block then raised beside the run's error)
- an `asyncio.Event` per run for that wait (about 1% of a run of one item: Measured)
