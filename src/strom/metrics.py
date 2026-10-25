"""Metrics: what a run reports while it runs, and the statistics of a run.

    recorder = StatsRecorder()
    async with stream(PIPELINE, inputs, pools, recorder=recorder) as outputs: ...
    stats = recorder.stats()                 # after the run; `print(stats)`: a table, a row per step occurrence
    for hint in diagnose(stats): ...         # e.g. the step that limits throughput: `hint.step_id`, `hint.message`

`stream(..., recorder=...)` passes the events of a run (`Event`: plain read-only data) to a `Recorder`, a
function of an event. Without a recorder (the default) nothing is measured: no clock is read and no event is
created (checked once per run).

  * `StatsRecorder` aggregates ONE run into `RunStats` (create one per run; `stats()` after the run;
    `stats.step(name)` for one step occurrence by name, e.g. a group "dup | neg"); `combine_recorders` feeds
    several recorders at once (e.g. statistics and an exporter); `diagnose(stats)` derives hints (bottleneck
    step, pool tasks waiting) as a pure function of the statistics.
  * A run lasts from entering its block to leaving it, so its wall time includes the consumer. A slow consumer
    shows as blocked (backpressure) time of the last step, which `diagnose` may then name as the step that
    limits throughput.
  * `RunStarted` lists the run's step occurrences (`StepId`: a position in the run's stage); per task of a step
    occurrence one `InputHandled` per input it took (its wait for input, busy and blocked (backpressure) time,
    outputs, and its `Outcome`: "done", "failed" or "cancelled" when the run failed elsewhere), then one
    `TaskFinished`; idle, busy and blocked time add up to the task's lifetime. For pool steps one
    `PoolTaskFinished` per pool task: the wait outside the function, running time and CPU time (measured in
    the pool worker as durations, valid across processes). `RunFinished` ends the run with its `Outcome`.
  * Times are readings of time.perf_counter on the event loop; pool workers measure durations with
    time.perf_counter and, for CPU time, time.thread_time.
  * A recorder of your own must not block, catches its own I/O errors and expects new event kinds and fields
    (`case _: pass`, match fields by keyword): the contract is the docstring of `Recorder`.
"""

from strom._metrics.events import (
    Enclosing,
    Event,
    InputHandled,
    Outcome,
    Part,
    PoolTaskFinished,
    Recorder,
    RunFinished,
    RunStarted,
    StepId,
    TaskFinished,
)
from strom._metrics.stats import Hint, RunStats, StatsRecorder, StepStats, combine_recorders, diagnose

__all__ = [
    "Recorder",
    "StatsRecorder",
    "combine_recorders",
    "RunStats",
    "StepStats",
    "diagnose",
    "Hint",
    "Event",
    "RunStarted",
    "InputHandled",
    "TaskFinished",
    "PoolTaskFinished",
    "RunFinished",
    "Outcome",
    "StepId",
    "Enclosing",
    "Part",
]
