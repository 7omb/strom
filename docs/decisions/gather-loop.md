# Gather and loop

`gather` and `loop` are separate kinds, like `Join`: a body plus a `Focus`, with a shared `_InFlight`. Their
`concurrency` is the number of inputs in flight, and their part is named `body`. A gather in a branch is counted
although it is always 1:1 (+1 and -1 cancel: an equivalent mutant), for uniformity.

**Rejected**

- on top of `route` (no cycle)
- bounded feedback with Parks-style deadlock detection (reason not recorded)
- FIFO feedback (model: peak 190 vs 14 items)
- no admission limit (unbounded queues)
- `buffer_size` as the limit (mixes capacity and in-flight inputs)
- part `left` (the body of a gather or loop is no branch: `docs/decisions/step-ids.md`)
