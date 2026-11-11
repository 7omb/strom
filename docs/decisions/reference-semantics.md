# Reference semantics

`run_reference` builds an ItemFn: lazy, depth-first; `evaluate` fails like a run (2026-11-05): ONE `RunFailed`
(`run_failed`, shared with the runner), the stage notes of a run (`stage_note`, shared; `_noted` around steps, joins,
routes, gathers and loops, not chains), except that the reference runs unfused and so names the step of a fused group,
not its chain. It knows no pools (2026-11-11): a leaf means the items of its function, lazily, whatever its resource
(`expanding`, `async_expanding`); where a function runs and how its items are delivered is a run's business

**Rejected**

- lists per chain part (diverged on endless sources, met other errors than runs)
- pool leaves through an offloader of its own (`item_fn_of(leaf, _DIRECT)`, until 2026-11-11: the reference imported the
  runtime for it, and its "cpu" leaf listed the items first, a difference no test could see: with every `Expand`
  evaluated as an event-loop leaf the suite passed unchanged)
