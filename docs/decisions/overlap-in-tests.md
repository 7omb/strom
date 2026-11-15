# Overlap in tests

Tests make steps overlap with barriers, events and `Tracker.saturating`, not with sleeps, because sleeps are slow and
depend on timing.

**Rejected**

- virtual-time loops (can't cover thread sleeps; unverified)
- a manual clock in real runs (non-deterministic interleavings)
