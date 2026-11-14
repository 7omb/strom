# Buffer size

The default `buffer_size` of the steps that wait (`io_stage`, `cpu_stage`, `async_stage`) stays 10, the size of the
step's output queue (`DEFAULT_BUFFER_SIZE` in `strom._stages.model`; event-loop steps size theirs from the consumer's
concurrency, `docs/decisions/fusion.md`): at concurrency 4 every kind is at its plateau by 10, and at concurrency 16 a
larger queue gains a few percent at most, less than the spread of the runs.

Measured 2026-11-13 (Python 3.14.8 with the GIL, pinned to the P-cores, 5 rounds with the sizes interleaved; µs per
item, medians; cpu on threads). Cheap: the step on 10,000 items, then `stage(neg)`. Jittered: the step and an `io_stage`
after it, both sleeping 0–2 ms per item in a fixed pattern, 400 items.

| Concurrency 4 | 1 | 2 | 4 | 10 | 20 | 50 |
| -- | -- | -- | -- | -- | -- | -- |
| cheap `io_stage` | 88.8 | 80.2 | 73.9 | 71.7 | 73.9 | 73.7 |
| cheap `cpu_stage` | 85.9 | 76.8 | 73.2 | 72.4 | 73.2 | 75.1 |
| cheap `async_stage` | 17.3 | 13.8 | 12.8 | 11.3 | 11.5 | 11.1 |
| jittered `io_stage` | 447 | 424 | 401 | 392 | 409 | 406 |
| jittered `cpu_stage` | 437 | 426 | 397 | 399 | 399 | 390 |
| jittered `async_stage` | 448 | 422 | 386 | 378 | 373 | 375 |

| Concurrency 16 | 4 | 10 | 16 | 32 | 64 |
| -- | -- | -- | -- | -- | -- |
| cheap `io_stage` | 68.3 | 64.9 | 60.0 | 62.8 | 61.6 |
| cheap `cpu_stage` | 66.8 | 63.0 | 61.3 | 61.3 | 61.4 |
| cheap `async_stage` | 13.4 | 12.9 | 12.8 | 12.6 | 11.4 |
| jittered `io_stage` | 155 | 154 | 153 | 153 | 147 |
| jittered `cpu_stage` | 153 | 150 | 154 | 151 | 148 |
| jittered `async_stage` | 108 | 107 | 111 | 107 | 96 |

The minimums scatter between two modes of the thread scheduling (about 2x apart, as in `docs/decisions/worker-pool.md`),
so the medians are the reading; differences of a few percent need `bin/ab.py`.

**Rejected**

- a default that grows with the step's concurrency, as the event-loop queues do (`max(10, 2 × concurrency)`): up to 8%
  for cheap io tasks at concurrency 16 by the medians, within the spread; not measured with `bin/ab.py`
