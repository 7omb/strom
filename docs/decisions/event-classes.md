# Event classes

Plain `@final` classes with `__slots__`, `__match_args__` and `Final` attributes; `RunStarted` (with the step
occurrences), one `InputHandled` per input a task took, whatever its `Outcome` (done, failed, cancelled), with its wait
and all counts; one `TaskFinished` per task whose coroutine ran (hence not `StepFinished`); `PoolTaskFinished`;
`RunFinished` with the run's `Outcome`. Both carry the task index `task`: per task, the events partition its lifetime
(each `wait_started_at` is the previous `ended_at`: one clock read per input and step less). Intervals end in
`ended_at`, closing events are `<Subject>Finished`; field names follow the naming conventions (`ARCHITECTURE.md`)
(2026-11-06)

**Rejected**

- `StepStarted` per step occurrence (static facts: `RunStarted.steps`)
- `Processed` and `Failed` (one fact in two events; a failed or cancelled input's outputs and time were lost)
- `failed: bool` (drops cancelled inputs, and a run's end needs another flag)
- `error: Exception | None` (keeps tracebacks alive in buffering exporters; may come later as a last field)
- durations instead of timestamps (spans need points in time)
- the partition per step occurrence only, without `task` (nobody could check it nor nest spans per task)
- recording a skipped pool task's input at once (a second cancelled path, idle time that was no wait)
- keyword-only constructors (not measured yet)
