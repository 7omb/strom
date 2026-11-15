# Generated stages

A generated stage gives at most `strategies.MAX_OUTPUTS` outputs per input, because the laws compose a generated stage
with itself, and its outputs multiplied (2026-11-12; how: its docstring in `tests/strategies.py`). A loop feeds items
back, and `interchange` applies a stage twice. Hypothesis's mutation phase built nests of `product`s over 1:3 leaves,
whose outputs multiplied by 3^k per pass.

**Measured** (2026-11-12)

- Five such leaves in `loop_unfolds` gave 16,593 outputs for one input (0.7 s), and one example took 434 s.
- All law tests ran 30 times, interleaved. On HEAD they took 390 and 76 s (slowest test 48 s, one ended by the timeout),
  with the bound 50 and 49 s (slowest 2.9 s).

**Rejected**

- a bound by measurement, `assume` on the outputs of a generated stage (a meaning per example, and it rejects examples
  only after they were built)
- fewer `max_leaves` (a nest of 1:3 leaves stays possible)
- `filter` for the bound (a retried draw puts the strategy's repr, 34 kB, into an event: a `HypothesisWarning`, an error
  here)
