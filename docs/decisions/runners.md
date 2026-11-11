# Runners

One runner, async only: `async with stream(stage, inputs, pools) as outputs: async for out in outputs` (named to pair
with `run_reference`); a feeder (`_feed`) puts the inputs into the queue of the stage's first step, which
`start_streaming` returns with the outputs (2026-11-05: the runner uses none of `streaming`'s internals); the inputs
belong to the caller and are not closed; an error of the inputs ends the run like a step's (failure flag set) without a
stage note; the outputs a class (`_Outputs`, several consumers may share it; one outside the block gets `RuntimeError`);
after a failure, a consumer that waits for an output waits for the end of the block (2026-11-11): one inside the block
is cancelled meanwhile, however deep in task groups, and one outside gets its error then; folds over a whole run are the
consumer's code; costs: see `runner-costs.md`

**Rejected**

- a sync runner (a loop driven from sync code costs 24 µs per resume, or a thread changes where event-loop functions
  run)
- a runner taking a fold (the consumer's code is the fold)
- an async generator as the outputs (no two consumers; PEP 789's hazard when iterated directly)
- closing the inputs
- a waiting consumer giving the block's cancellation one loop iteration before it takes itself for one outside the block
  (until 2026-11-11: the cancellation takes an iteration per task group around the consumer, so from three groups on the
  consumer raised the `RuntimeError`, which the block then raised beside the run's error)
- an `asyncio.Event` per run for that wait (`run_overhead_one_item` 1.012 and 1.005, p 0.044 and 0.007; made by the
  first consumer that waits instead: 0.998 and 0.987, p 0.42 and 0.31; `bin/ab.py`, `BENCH_SCALE=0.5`, 15 interleaved
  runs pinned to the P-cores, 2026-11-11)
