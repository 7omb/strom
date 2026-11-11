# Runner costs

Accepted for now (2026-11-05): a run whose first step is an event-loop step costs about twice as much per input as with
a source (against the last state with sources, `bin/ab.py`, 9 interleaved runs, e.g. 1 event-loop step 2.96 → 5.70 µs
per input; `async_stage`, `io_stage`, `product(stage, stage)` 0.98–1.05): the step handles each input with an async
generator (1.80 vs 0.18 µs per input for iterating the result directly). `stream` adds 1–3% per input for the cheap rows
(async iteration of the outputs) and about 42 µs per run (its task group, run task and future). Measurements and the
fix: `docs/plans/event_loop_step_cost.md`

**Rejected**

- an internal source-like step in the runner fused with the stage's first steps (fixes only the first step of a run; its
  name in group names and stage notes)
