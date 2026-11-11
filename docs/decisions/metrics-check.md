# Metrics check

`recorder=None` is off, checked once per run; ONE task loop for all steps, recording under local `if recording` checks
(no clock reads, no events when off). Cost of recording with a `StatsRecorder`, one fused step per input (2026-11-06,
`bin/ab.py -- -k recording`, 9 runs each): 3.6 µs before the events of `InputHandled`, 4.0 µs with them (recorded rows
+2.2% and +4.7% for `product`, p ≤ 0.003; unrecorded rows unchanged, p 0.45 and 0.97)

**Rejected**

- an `Enabled` token from `enabled()` (forgeable, accepted by any recorder, unused by them; `NoRecorder` had only dead
  methods)
- always calling a no-op recorder (0.28 µs per item and step)
- separate loops per variant (duplicated; hand-specialised loops were 2–7% faster unrecorded, 15% slower recorded for
  lifted steps)
- variants generated from one template by pruning its AST (needs `inspect.getsource` at run time; hidden machinery)
- unlifted steps without a focus (`None`: two type escapes)
