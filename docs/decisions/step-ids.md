# Step ids

A step id is the step occurrence's position in the stage, a path, because a number in start order followed the task
scheduling: branch steps came after later steps. The order of the stage comes from `RunStarted.steps` (`step_ids`, a
pure walk of the fused stage that mirrors `_run_streaming`); a property test checks that the events' ids equal it.

**Rejected**

- a pre-order number (needs subtree sizes, loses the branch)
- a path over the binary chain (`(a|b)|c` ≠ `a|(b|c)`)
- numbering a rebuilt stage (one step object can sit in two places)
- `order=True` (left before right only alphabetically)
- `Side` as an enum (extra public class)
- the names `Branch`/`Side` for the enclosing stage and the part (the body of a gather or loop is no branch:
  `Enclosing`/`Part`, 2026-11-06)
- a position-only `StepId` (public API change for no defect; `name` and `concurrency` describe the position)
- caching its hash (recording: within noise)
- an explicit pre-order sort key `preorder` (redundant once `RunStarted.steps` carries the order, 2026-11-06)
- collecting the ids while starting (joins, routes, gathers and loops start their parts lazily: a barrier in every
  combinator)
