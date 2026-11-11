# Tasks of an element

Every element of a run's stage (a step occurrence, a join, a route, a gather, a loop) starts its tasks through one
function, `start_tasks` (`strom._interpreters.run_context`, 2026-11-11): a task group of their own, the stage note on
their errors, the end of their output stream. A step passes no name: its tasks note their errors where they set the
failure flag. Measured (`bin/ab.py`, `BENCH_SCALE=0.5`, 15 interleaved runs pinned to the P-cores, 2026-11-11): the
`run_overhead_one_item`, `product_stages` and `recording` rows within noise (p ≥ 0.065), but for one bimodal row of the
thread backend (0.56, p 0.019, an IQR as large as its median)

**Rejected**

- that frame written out per kind (five copies until 2026-11-11)
- an async context manager around a kind's own task group (a join checks that every input is complete between the end of
  its tasks and the handling of their errors: after such a block the check would neither be noted nor come before the
  end of the stream)
