# Gather, loop

Own kinds like `Join` (body plus `Focus`), shared `_InFlight`; `concurrency` = inputs in flight; part `body`. A gather
in a branch is counted although always 1:1 (+1/-1 cancel: equivalent mutant), for uniformity

**Rejected**

- on top of `route` (no cycle)
- bounded feedback with Parks-style deadlock detection
- FIFO feedback (model: peak 190 vs 14 items)
- no admission limit (unbounded queues)
- `buffer_size` as the limit (mixes capacity and in-flight inputs)
- part `left`
