# Step ids

Position path; the order of the stage from `RunStarted.steps` (`step_ids`, a pure walk of the fused stage mirroring
`_run_streaming`; a property test checks that the events' ids equal it, 2026-11-06)

**Rejected**

- numbering in start order (followed task scheduling: branch steps came after later steps)
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
