# `product`

`product` takes any two stages and runs them as two independent streams, joined per input by sequence numbers
(`lift_sequenced`), because `first(f) | second(g)` has the latency of f plus that of g. Every branch step is counted,
with one count per branch: a branch's results of an input are kept only while the other branch is not done with it. Each
pair is merged when it can be put, so in flight are the output queue's capacity and one pair (`ARCHITECTURE.md`,
Concurrency and pools).

**Rejected**

- merging all pairs of a result before putting them (a late result meeting 100,000 stored ones peaked at 11.2 instead of
  4.1 MB, 2026-11-01)
- indexing the input pair (a non-pair input was silently cut to two elements; unpacking raises in both interpreters)
- one count for both branches (kept every result until the input was complete: 100,000 of 100,000 left outputs of one
  input, 2026-11-01)
- Maps only (1:1 special cases throughout)
- skipping the count for 1:1 steps (needs 1:1 detection; counting costs about 1.3 µs per branch step and item)
- per-item evaluation (slower)
- position-based matching (wrong with a concurrency above 1)
- an OO `_JoinParts` ABC (OO mixes the stage and its execution: `docs/decisions/architecture.md`)
- `product(J, identity())` lifting (endless recursion)
