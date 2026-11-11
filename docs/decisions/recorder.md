# Recorder

Events as data (a recorder's error ends the run like a user's error and never hides the run's own error):
`Recorder = Callable[[Event], None]`, `StatsRecorder` a fold, `combine_recorders` a fan-out; fixed clocks, not
parameters (2026-11-07): `time.perf_counter` on the event loop and for durations in pool workers, `time.thread_time` for
CPU time; the tests check the partition by the chain of readings (each `wait_started_at` is the previous `ended_at`) and
the folded totals with `math.isclose`, and times by lower bounds of intentional sleeps. A recorder whose `RunStarted`
returned gets exactly one `RunFinished`, one that raised none; `combine_recorders` keeps that for its children like
`ExitStack` (2026-11-06). `StatsRecorder` is single-use (a second `RunStarted` raises, failing that run at its start;
`stats()` only after `RunFinished`, 2026-11-06). The contract (no blocking, own I/O errors, events may grow) is the
`Recorder` docstring

**Rejected**

- per-run and per-step handles (safe call order, but more public names)
- clocks as run parameters `stream(..., clock=, cpu_clock=)` (2026-11-06 to 2026-11-07; only tests passed one: a clock
  that can't be pickled failed recording runs only on backends without shared memory, a decreasing one gave negative
  times unchecked, a `ManualClock` pickled to a worker stood still; Trio's `clock=` drives its scheduler, strom's only
  timestamped events)
- the event loop's `loop.time()` (a Python method: 145 vs 91 ns per reading, 2026-11-07; pool workers have no loop, so a
  virtual-time loop would mix virtual and real time in `pool_wait_time`; uvloop's is coarse [unverified])
- a private module-level clock monkeypatched by tests (a global seam, and the plumbing stays)
- clocks on the recorder (a combined recorder silently overrode its children's clocks)
- isolating recorder errors (Trio disables, OpenTelemetry swallows: incomplete metrics nobody notices)
- a `Clock` protocol with `now()` and clock classes (four public names for two functions)
- bundling recorder and clocks in a `Metrics` class (longer common case, one more public class, fixes only a clock
  passed without recorder)
- `RunFinished` after every attempted `RunStarted` (a `StatsRecorder` refusing a second run would take its `RunFinished`
  for its own run's end)
- a run id on every event so one `StatsRecorder` folds concurrent runs (a field per input event for a rare case)
- a reusable `StatsRecorder` with a reset (an overlapping run cleared the first run's totals, which then failed far from
  the cause)
- only the first error when several children raise on `RunFinished` (hides the others)
