# Closing outputs

Consumers of an ItemFn close its generator only when they stop early (`except BaseException`); an ended async generator
is closed already

**Rejected**

- `aclosing` per input (A/B, 15 processes per variant: 6 inline steps 11.70 → 8.75 µs per item, `first(stage)` 3.87 →
  2.98, `product(stage, stage)` 10.62 → 8.76)
