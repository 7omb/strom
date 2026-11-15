# Metrics check

Metrics are off with `recorder=None`, which a run checks once, so that an unrecorded run reads no clock and creates no
event. One task loop serves all steps and records under local `if recording` checks.

**Measured** (2026-11-06, `bin/ab.py -- -k recording`, 9 runs each): recording with a `StatsRecorder` costs 3.6 µs per
input of one fused step before the events of `InputHandled` and 4.0 µs with them. With them the recorded rows rose by
2.2%, and by 4.7% for `product` (p ≤ 0.003); the unrecorded rows did not change (p 0.45 and 0.97).

**Rejected**

- an `Enabled` token from `enabled()` (forgeable, accepted by any recorder, unused by them; `NoRecorder` had only dead
  methods)
- always calling a no-op recorder (0.28 µs per item and step)
- separate loops per variant (duplicated; hand-specialised loops were 2–7% faster unrecorded, 15% slower recorded for
  lifted steps)
- variants generated from one template by pruning its AST (needs `inspect.getsource` at run time; hidden machinery)
- unlifted steps without a focus (`None`: two type escapes)
