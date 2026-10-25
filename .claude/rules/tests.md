---
paths:
  - "tests/**"
  - "benchmarks/**"
  - "examples/**"
---

# Tests and benchmarks

Conventions for tests: `ARCHITECTURE.md`. How a change to tests is checked (collected IDs, injected bugs): skill
`validate-change`.

## Testing notes

- Every sleep must be intentional; a docstring where it occurs explains why it is needed.
- Async tests run on pytest-asyncio (`asyncio_mode = "auto"`, a loop per test): a test that uses the `pools` fixture or
  `outputs_of` is `async def` (the reference semantics there: `helpers.meaning_async`); never call `asyncio.run` inside
  one. Hypothesis tests stay sync on `helpers.collect`/`meaning`/`stats_of`, each an `asyncio.run` with its own pools
  (`meaning` is `testing.evaluate`: not inside an async test).
- CPython closes unreferenced generators by garbage collection and the event loop closes async generators at shutdown.
  Tests of closing therefore keep a reference, inspect the generator state (`endless_stage`) and check inside the
  running loop; otherwise a missing `close()` goes unnoticed.
- Closing through wrapper generators is masked by reference counting (an unreferenced wrapper closes what it delegates
  to): closing tests use closable non-generator iterators or kept references.
- A pool thread goes idle a moment after the result of its call is out, and until then the next call without affinity
  starts another thread (or worker process). A test that says which thread or process takes a call waits for the idle
  state (`wait_until_idle` in `tests/runtime/test_pinning_pool.py`) or uses one worker (2026-11-11: two tests comparing
  pids on a two-worker backend failed in one of three suite runs).
- An `io_stage` function that returns a list or a tuple registers no iterator: a test of streaming, of affinity or of
  releases needs a function that returns an iterator (`at_most_three_lazily`, a generator, a closable iterator class);
  with a list it passes without testing anything (2026-11-11).
- Count the pool tasks submitted to a backend with `helpers.CountingThreads`; it starts `run` eagerly, so its count is
  never ahead of what is queued (2026-11-11: counting after an `await asyncio.sleep(0)` came too late for inputs that
  wait for the count).
- An injected bug that a narrow `-k` reports as `missed` may be caught by a test elsewhere: run it against the whole
  suite (`bin/mutant.py … -- -q -n auto`) before writing a test for it (2026-11-11: a check run also after an error
  passed `-k product` in `test_streaming.py`, whose failing products have one input, and failed
  `test_skipped_tasks_do_not_end_a_stream_early` in `tests/interpreters/test_offloaders.py`).

## Benchmarks

One measurement per test (a second `benchmark()` call fails), grouped with `pytest.mark.benchmark(group=…)` so a
reference and the pipeline share a table; ratios between benchmarks with different item counts are not comparable. A 10%
`--benchmark-compare-fail` flagged an unchanged benchmark in the noisy sandbox: tune it on the target machine.

```
uv run pytest benchmarks/benchmark.py [--benchmark-autosave | --benchmark-compare --benchmark-compare-fail=min:10%]
BENCH_SCALE=0.2 uv run pytest benchmarks/benchmark.py --benchmark-min-rounds=1 --benchmark-max-time=0.1
uv run pytest benchmarks/benchmark.py --benchmark-disable   # each benchmark once, no timing: results only
```

A recorded measurement names its baseline by a tag, never by a commit hash: a rewritten history leaves a hash on the
reflog only (2026-11-10: a squash did that to three cited commits). Tag the revision before citing it:
`git tag baseline/<date> REV` (lightweight: the jail has no git identity for an annotated one); `bin/ab.py` takes the
tag as a revision. It runs the working tree's benchmarks on both sides, so a baseline serves as long as it has the names
they import. A tag reaches a clone when it is pushed, which is the user's step (`git push origin TAG`). The baselines
(`git tag -l 'baseline/*'`):

| Tag | The state it keeps |
| -- | -- |
| `baseline/2026-11-11` | the built-in backends on a pool of their own, the metrics in `strom.metrics` |

The measurements before it name their state in words and by date: those states went with the squashed history.
