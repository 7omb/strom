# Closing outputs

Consumers of an ItemFn close its generator only when they stop early (`except BaseException`), not with `aclosing` per
input, because an ended async generator is closed already, and closing every one costs a fifth to a third more per item.

**Measured** (A/B, 15 processes per variant; µs per item)

| Stage | `aclosing` per input | closed when stopped early |
| -- | -- | -- |
| 6 inline steps | 11.70 | 8.75 |
| `first(stage)` | 3.87 | 2.98 |
| `product(stage, stage)` | 10.62 | 8.76 |
