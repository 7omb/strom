# Overlap in tests

Barriers, events, `Tracker.saturating`

**Rejected**

- sleeps (slow, timing-dependent)
- virtual-time loops (can't cover thread sleeps) [unverified]
- a manual clock in real runs (non-deterministic interleavings)
