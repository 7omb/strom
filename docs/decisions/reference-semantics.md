# Reference semantics

`run_reference` builds an ItemFn that is lazy and depth-first, and it knows no pools: a leaf means the items of its
function, lazily, whatever its resource, because where a function runs is a run's business.

- A leaf is evaluated by `expanding` or `async_expanding`; how its items are delivered is a run's business as well.
- `evaluate` fails like a run: one `RunFailed` (`run_failed`, shared with the runner) with the stage notes of a run
  (`stage_note`, shared; `_noted` around steps, joins, routes, gathers and loops, not chains).
- The reference runs unfused, so it names the step of a fused group, not its chain.

**Rejected**

- lists per chain part (diverged on endless sources, met other errors than runs)
- pool leaves through its own offloader (`item_fn_of(leaf, _DIRECT)`, until 2026-11-11: the reference imported the
  runtime for it, and its "cpu" leaf listed the items first, a difference no test could see: with every `Expand`
  evaluated as an event-loop leaf the suite passed unchanged)
