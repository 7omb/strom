---
paths:
  - "tests/runtime/**"
  - "tests/interpreters/**"
  - "tests/helpers.py"
---

# Tests of pools and runs

- A test that says which thread or process takes a call waits for the idle state first (`wait_until_idle` in
  `tests/runtime/test_pinning_pool.py`) or uses one worker, because a pool thread goes idle a moment after the result of
  its call is out, and until then the next call without affinity starts another thread or worker process (2026-11-11).
- A test of streaming, of affinity or of releases needs an `io_stage` function that returns an iterator
  (`at_most_three_lazily`, a generator, a closable iterator class), because one that returns a list or a tuple registers
  no iterator: with a list the test passes without testing anything (2026-11-11).
- Count the pool tasks submitted to a backend with `helpers.CountingThreads`; it starts `run` eagerly, so its count is
  never ahead of what is queued (2026-11-11: counting after an `await asyncio.sleep(0)` came too late for inputs that
  wait for the count). A task wrapped around its `run` starts eagerly too (`ShieldingThreads` in
  `tests/test_runners.py`, 2026-11-13).
- A test that needs a pool task running waits for an event that its function sets, also in inputs that fail on the
  count, because a pool task that is counted as submitted has not started: its thread may take it later, and then not
  run it, when the run has failed or its caller is cancelled (2026-11-14).
- For a task that outlives its cancelled caller, use `asyncio.wait([task])` and a done callback that retrieves its
  error, not `asyncio.shield`, which reports that error to the loop's exception handler (3.14, "exception in shielded
  future": an ERROR log in a passing test, 2026-11-13).
