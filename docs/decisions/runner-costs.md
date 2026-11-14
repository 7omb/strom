# Runner costs

Accepted (2026-11-13): an event-loop step, or a fused group of them, pays about 0.8 µs per input it takes from a queue
for an async generator that wraps the outputs of that input (`expanding` in `strom._interpreters.item_fns`, `_fair` in
`strom._interpreters.fusion`): the task loop iterates every step's outputs as an `ItemFn`, one async interface for the
leaves that wait and those that don't (`_run_step_tasks` in `strom._interpreters.steps`). It is visible only in runs of
cheap event-loop steps on many inputs; next to a pool step it is below the variation of the pool's latency. Iterating
the sync function directly would take a second inner loop in the task loop, and for groups a carrier of their sync
function on the leaf: more code on the hottest path than the gain justifies. To reconsider when a use needs the
throughput of runs made only of event-loop steps. `stream` adds 1–3% per input for the cheap rows (async iteration of
the outputs) and about 42 µs per run (its task group, run task and future).

Measured 2026-11-13 (Python 3.14.8 with the GIL, pinned to the P-cores, minimum of 15 interleaved runs, the medians
within 3%; probes in `.checks/probes/`, `b2_*`), µs per item:

| Stage | 50,000 inputs | one input making them |
| -- | -- | -- |
| `identity()` | 2.31 | 1.39 |
| `stage(neg)` | 2.37 | 1.41 |
| `identity() \| stage(neg)` (a group of 2) | 3.81 | 1.81 |
| `stage(neg)` three times (a group of 3) | 4.18 | 2.18 |

- Per input outside a run: an async generator iterated with `async for` 0.78 µs (`expanding`), 0.80 (`_fair`); iterating
  `fn(item)` directly 0.05; a `get_nowait` from the input queue 0.13. A group's composed function (`_then`): 0.07 / 0.34
  / 0.72 µs directly for 1 / 2 / 3 members, 0.82 / 1.19 / 1.59 through `_fair`.
- Next to pool steps (20,000 inputs, minimum of 9): `stage(neg) | where(is_odd)` 3.37 µs per item;
  `io_stage(inc, concurrency=8)` 53.1, with those two steps after it 31.4; `cpu_stage(inc, concurrency=4)` on threads
  25.1, with them 29.1. The 0.8 µs are 2–3% there, less than the difference between two runs of the same pool step.
- Fusion is idempotent: a run of `fused(stage)` (which fuses again) has the step occurrences and outputs of a run of
  `stage`, on 300 generated stages, 119 with a group: a group's leaf is `AsyncExpand`, never a member.

**Rejected**

- an internal source-like step in the runner fused with the stage's first steps (fixes only the first step of a run; its
  name in group names and stage notes)
- a sync ItemFn for event-loop leaves, iterated by a second inner loop of the task loop, with a group's sync function
  carried by a callable class on its `AsyncExpand` leaf, told apart by a generic `TypeIs` guard (a class pattern loses
  the type parameters in all three checkers): 0.8 µs per input of event-loop steps for a second code path of closing,
  cancellation, fairness (SKIPs) and blocked time on the hottest path; and the same for single steps only, without the
  carrier (the second loop for single steps alone)
- a group as an `Expand(resource=None)` leaf whose function emits SKIPs (a group would be an event-loop step again:
  fusion idempotent only through a marker check in `_event_loop_fn`)
- a private leaf kind for groups (an arm in every `match` on `Leaf` for what `AsyncExpand` carries already)
- separate task loops per leaf kind (duplicated code, `docs/decisions/metrics-check.md`)
