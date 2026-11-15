# Event classes

The events of a run are plain `@final` classes with `__slots__`, `__match_args__` and `Final` attributes, and per task
they partition its lifetime, so that a test can check them and an exporter can nest spans per task.

- `RunStarted` holds the step occurrences.
- One `InputHandled` stands for each input a task took, whatever its `Outcome` (done, failed, cancelled), with its wait
  and all counts.
- One `TaskFinished` stands for each task whose coroutine ran (hence not `StepFinished`).
- `PoolTaskFinished` stands for a pool task, and `RunFinished` carries the run's `Outcome`.

`InputHandled` and `TaskFinished` carry the task index `task`. Each `wait_started_at` is the previous `ended_at`, which
saves one clock read per input and step. Intervals end in `ended_at`, closing events are `<Subject>Finished`, and field
names follow the naming conventions (`ARCHITECTURE.md`).

**Rejected**

- `StepStarted` per step occurrence (static facts: `RunStarted.steps`)
- `Processed` and `Failed` (one fact in two events; a failed or cancelled input's outputs and time were lost)
- `failed: bool` (drops cancelled inputs, and a run's end needs another flag)
- `error: Exception | None` (keeps tracebacks alive in buffering exporters; may come later as a last field)
- durations instead of timestamps (spans need points in time)
- the partition per step occurrence only, without `task` (nobody could check it nor nest spans per task)
- recording a skipped pool task's input at once (a second cancelled path, idle time that was no wait)
- keyword-only constructors (not measured yet)
