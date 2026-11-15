# `io_stage` items

How the items of an `io_stage` function come follows what it returns, not only the resource: an iterator is streamed, a
list or a tuple comes whole, because it has nothing to stream.

- An iterator takes one pool task per item, the first also calling fn, plus one that finds the end (`_opened`).
- A list or a tuple comes whole, in the one pool task that calls fn, with nothing registered. `open_iterator` dispatches
  on what the function returned, as the feeder does on `AsyncIterable`.
- `using` keeps the shape: a list's use of its handle ends when fn returns.
- Users batch lazy iterators themselves if needed.

**Measured**

- `_opened`, a `1:1` `io_stage` at concurrency 4: 100–134 → 70–71 µs per item.
- A cheap item costs about 41 µs streamed and 1.35 µs collected first.
- The 1000 items of one list took 1001 pool tasks and 160 ms before, one pool task and about 5 ms after (2026-11-11,
  recorded runs, machine not idle).
- A 1:1 function returning a one-item list takes one pool task per input instead of two.

**Rejected**

- fixed batches (latency for slow iterators)
- time-limited batches (more code, two constants)
- every in-memory collection whole (`Collection`, `Sequence`: a lazy one, such as a query set, would be iterated on the
  event loop; a subclass of list or tuple is taken for what it is)
- a delivery parameter on the factories (see `docs/decisions/resources.md`)
