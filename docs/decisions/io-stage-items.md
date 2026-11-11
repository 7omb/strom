# `io_stage` items

An iterator: one pool task per item, the first also calling fn, plus one finding the end (`_opened`: 1:1 `io_stage` c=4
100–134 → 70–71 µs per item; about 41 µs vs 1.35 µs per cheap item collected first). A list or a tuple (2026-11-11):
whole, in the one pool task that calls fn, with nothing registered (`open_iterator`, a dispatch on what the function
returned, like the feeder's on `AsyncIterable`): it has nothing to stream, so how the items come follows the value, not
only the resource. `using` keeps the shape (a list's use of its handle ends when fn returns). Measured (2026-11-11,
recorded runs, machine not idle): the 1000 items of one list in 1001 pool tasks and 160 ms before, one pool task and
about 5 ms after; a 1:1 function returning a one-item list takes one pool task per input instead of two. Users batch
lazy iterators themselves if needed

**Rejected**

- fixed batches (latency for slow iterators)
- time-limited batches (more code, two constants)
- every in-memory collection whole (`Collection`, `Sequence`: a lazy one, such as a query set, would be iterated on the
  event loop; a subclass of list or tuple is taken for what it is)
- a delivery parameter on the factories (see `resources.md`)
