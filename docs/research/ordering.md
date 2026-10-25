# Ordered outputs – strom

Research of 2026-11-08: how a building block that restores the order of outputs could be designed, which established
mechanisms it could reuse or adapt, and whether better algorithms exist. Follows gap 2 of `docs/research/features.md`. A
new combinator is an addition to the public API and needs the user's go-ahead. Claims about other libraries that weren't
checked against their sources are marked [unverified].

## The problem

A run's outputs are a bag (user guide, Order). With `concurrency=1` everywhere, the order is that of the reference
semantics: depth-first, per input in the order of `inputs`. That is the list monad's order:
`(f | g)(x) = concatMap g (f x)`. Any `concurrency > 1`, `product`, `route` or `loop` gives that order up. Users need
order back for logs, sorted files, results by row number, or order per entity (all events of one customer in order).

Two kinds of order:

- **Order between inputs**: all outputs of input i before any output of input i+1.
- **Order within an input**: the outputs of one input in depth-first order, the list the reference semantics gives.

## Mechanisms in other libraries

| Library | Mechanism | Granularity |
| -- | -- | -- |
| Akka/Pekko Streams | `mapAsync(n)` keeps a buffer of n futures in input order and emits the head once it completes; `mapAsyncUnordered(n)` emits on completion | per step |
| Akka/Pekko Streams | `mapAsyncPartitioned(n, partitioner)`: ordered within a partition key [unverified: added in Akka 2.8 and Pekko 1.1] | per step, per key |
| Rust `futures` | `buffered(n)` (ordered, `FuturesOrdered`, a binary heap keyed by index) and `buffer_unordered(n)` [heap: unverified] | per step |
| CPython `multiprocessing.Pool` | `imap` (an index per task, a dict of results that arrived early and a cursor `_index`; mpire's `imap` likewise [unverified]) and `imap_unordered` | per map |
| Intel oneTBB `parallel_pipeline` | filter modes `serial_in_order`, `serial_out_of_order`, `parallel`; tokens bound the items in flight; a `serial_in_order` filter handles items in the order the first serial filter saw them | at chosen filters |
| Java Streams | `forEachOrdered` and ordered parallel streams: order is a stream property, `unordered()` drops it | whole stream |
| Ray Data | `DataContext.execution_options.preserve_order` | whole dataset |
| pypeln | `ordered` sorts by the original index, buffering the whole stream [unverified] | whole stream |
| Kafka, Kafka Streams | order per partition (key); the Confluent Parallel Consumer processes in parallel in key order or unordered | per key |
| Flink, Beam | no order across parallel instances; order by event time through windows and watermarks | event time |

Two mechanisms recur:

1. **A reorder buffer with sequence numbers.** This is TCP's receive buffer and the reorder buffer of out-of-order CPUs
   (Smith and Pleszkun 1985). Each item gets a number when it enters, results go into a buffer, and a cursor emits them
   in order. The window (n in flight) bounds memory and head-of-line blocking.
2. **Order as a key relation.** Order per key (Kafka partitions, `mapAsyncPartitioned`) blocks only items with the same
   key. A constant key is a total order; a unique key means no order.

## What strom already has

`gather` and `loop` already do most of the work (`src/strom/_interpreters/streaming.py`):

- `_InFlight` admits inputs one by one, numbers them consecutively (`sequence`), and bounds the inputs in flight
  (`concurrency`).
- `lift_sequenced` pushes counting down onto every step of the body (`counting_focus`, `counted`). Each input knows how
  many of its items are inside the body, and `complete(sequence, kept)` fires once there are none. This is exact
  completion tracking per input, as Naiad's progress tracking has for timestamps. No heuristics such as watermarks or
  K-slack are needed.
- `gather` collects the outputs of each input and emits the list when the input completes, in order of completion.

So `gather(f)` emitting its lists in sequence order, followed by `flatten()`, would already order between inputs. The
design below improves on that: it streams the head input instead of waiting for it to complete.

## Design: `ordered(f)`

```
ordered(f, *, concurrency=DEFAULT_IN_FLIGHT, buffer_size=DEFAULT_BUFFER_SIZE) -> Stage[I, O]
```

Meaning: as a bag, `ordered(f)` equals `f`. As a sequence, all outputs of input i come before those of input i+1. Within
an input, outputs keep the order in which they leave `f`.

A new stage kind `Ordered` (body plus `Focus`, like `Gather`) shares `_InFlight` and `lift_sequenced`. Its interpreter
differs from `_run_streaming_gather` only in what it emits:

```
head = 0                     # the sequence number of the oldest input not yet fully emitted
early: dict[int, list[B]]    # outputs of inputs after head (dense numbers: a dict plus cursor, no heap)
completed: set[int]          # inputs after head that are complete

on output (b, seq):          # the one loop taking the body's outputs
    if seq == head: put merge(b, kept)          # the head streams at once
    else:           early[seq].append(b)
    count(seq, -1)
on complete(seq):            # through an event queue, as gather's ready queue: `finish` cannot put
    completed.add(seq)
    while head in completed:
        completed.remove(head); release()       # the window moves: admit may take another input
        head += 1
        put each b of early.pop(head, [])       # the next head's early outputs, then it streams
```

Properties:

- **Window.** `concurrency` counts inputs from the head, and a slot is released when its input has been fully emitted,
  not when it completes. This is Akka's `mapAsync(n)` semantics: memory holds the early outputs of at most
  `concurrency - 1` inputs (times their outputs per input). It is the same bound gather has for its lists.
- **Latency.** The head input streams through with no extra wait. Only inputs that overtake it are buffered. With
  `gather | flatten` the head would wait for its own completion.
- **No deadlock.** The collecting loop takes every body output, whatever its input, and never waits for a particular
  one. A full output queue only applies backpressure to the body (as in a step). Feedback never waits, as in `loop`.
- **Within an input.** One step handles one input in one task, so a single step's outputs of one input leave in
  generator order (`io_stage`: one pool task after the other). Hence `ordered(step)` gives the full list order of that
  step.

### Full depth-first order by composition

Order between inputs on each step is enough for depth-first order overall. If the stream into `ordered(g)` is in
`concatMap f xs` order and `ordered(g)` keeps the order of its inputs, the result is `concatMap g (concatMap f xs)`, the
reference semantics' order. So:

```
ordered(f) | ordered(g)   # full depth-first order when f and g are single steps
ordered(f | g)            # order between inputs only; within an input, f's outputs may overtake each other in g
```

Laws (on sequences; the bag laws hold anyway):

- `ordered(ordered(f)) = ordered(f)`.
- `ordered(s1) | ... | ordered(sn) = evaluate(s1 | ... | sn)` as lists, for single steps `si`. This is directly testable
  against `strom.testing.evaluate` as a list, not as a bag.
- Fused event-loop steps keep order already, so `ordered` around a fused group costs no buffer inside it.

A helper could push `ordered` down onto every step, as lifting pushes focuses down (an `in_order(stage)` pass). For
`product`, `route` and `loop` it needs a rule for each kind (below). Leave that for later: it is more API, and wrapping
steps by hand covers the cases seen so far.

### Order per key

```
ordered(f, key=lambda x: x.customer_id)
```

Replace the single `head` by a queue of sequence numbers per key. An input is emitted when it heads its key's queue;
outputs of other keys pass at once. `key=None` (the default) is one key, which is total order. This is
`mapAsyncPartitioned` and Kafka's per-partition order. Head-of-line blocking then hits only inputs with the same key. A
slow head can still fill the window with later inputs of its own key and stall every key, which a limit per key would
prevent. Measure before adding that limit.

### Fit with the library

- **Stage encoding.** A new kind `Ordered` adds an arm to every dispatcher: lifting (three), fusion, `step_ids`,
  display, reference, streaming. `test_every_stage_kind_goes_through_every_dispatcher` catches a missing arm. Lifted
  onto pairs or into a branch, it is counted as one step, like `Gather` (`counted` around its focus).
- **Reference semantics.** `ordered(f)` evaluates as `f`: the reference order already is the list order.
- **Fusion.** A boundary, like `gather`.
- **Metrics.** A body part (`Enclosing(…, "body")`) like `gather`. Useful later: the time outputs wait in the buffer,
  the size of the buffer, and how long the head blocks.
- **Combinator, not a run option.** A `stream(..., ordered=True)` would be a second spelling of `ordered(stage)`.
  Per-step flags (`io_stage(..., ordered=True)`) would spread ordering into every factory and every step loop.
- **Cost.** Counting costs about 1.3 µs per body step and item (`docs/decisions.md`, `product`), plus one queue hop per
  output and a dict operation per early output. To measure: A/B against `gather(f) | flatten()` and against `f` alone.

## Alternatives considered

| Alternative | Verdict |
| -- | -- |
| `gather(f)` in sequence order plus `flatten()` | Correct and nearly free to build, but the head input waits for its own completion and keeps its whole list. A fallback if `Ordered` is not wanted. |
| An ordering flag per step (TBB `serial_in_order`, Akka `mapAsync`) | Every step pays, the flag goes into every factory, and joins and routes need their own rules. `ordered(step)` expresses it. |
| `stream(..., ordered=True)` | A second way to say `ordered(stage)`; it can't order a part of a stage. |
| Hierarchical sequence numbers (Dewey paths `i.j.k`, one per step output) with ONE buffer at the boundary | Restores full depth-first order inside `ordered(f \| g)` with one window. But every item carries a growing path, every step numbers its outputs, and completion must be tracked per path prefix (a tree of counters). `ordered(f) \| ordered(g)` gives the same order with flat numbers. Only worth it if one window across a long chain proves much faster. |
| A heap keyed by sequence number (Rust's `FuturesOrdered`) | Not needed: numbers are dense and consecutive, so a dict plus cursor is O(1) per item (CPython's `IMapIterator` does this). A heap fits sparse keys, e.g. sorting by a user key. |
| Sorting the whole stream at the end (pypeln's `ordered` [unverified]) | Not streaming; memory of the whole run. |
| Watermarks, punctuations, K-slack (Babcock et al.; Li et al. 2008, out-of-order processing) | For event time with unknown disorder. strom knows exactly when an input completes, so it needs no guesses. K-slack would fit a later `sort_within(key, slack)` by a user's timestamp. |
| Optimistic output with retractions (out-of-order processing with revisions) | Consumers of an async iterator can't retract. |

## Better algorithms?

For restoring a known order, the reorder buffer is optimal in what it holds. An item can only be released once
everything before it has been released, so the buffer holds exactly the outputs that overtook the head. Improvements
come from changing the problem, not the buffer:

- **Weaker order.** Order per key (above) is the biggest lever. Head-of-line blocking shrinks to items of the same key.
- **Window size.** Throughput under ordering depends on how much per-input latency varies, not on the mean. Queueing
  theory studies this as the resequencing problem (Baccelli, Gelenbe and Plateau 1984, "An end-to-end approach to the
  resequencing problem", J. ACM [unverified]; Harrus and Plateau 1982). The resequencing delay grows with the variance
  and the number of parallel servers, and a larger window absorbs it. Heavy-tailed latencies (retries, slow pages) are
  where an ordered pipeline loses most. An adaptive window or a metric for head-of-line time would show it.
- **Avoid overtaking at the source.** Scheduling the oldest input first in shared pools would shrink the buffer. strom's
  pool queues are FIFO already, and a step task takes its input before it submits, so little is gained.
- **Ordering earlier vs. later.** One `ordered` at the end gives the body the most freedom (largest slack). Per-step
  ordering stalls each step on its own head. To get order between inputs, prefer one boundary. Use per-step wrapping
  only where order within an input matters.

## Open questions for a decision

- Name: `ordered` (reads as a property) vs. `in_order` vs. `sequential`. `sequential` is misleading: the body stays
  concurrent.
- Should `concurrency` default to gather's `DEFAULT_IN_FLIGHT`, or is a larger window better for ordering? Measure.
- `key=` in the first version, or later?
- Should `gather` take its order from the same machinery (`gather` emitting in input order would make `gather(f)`
  deterministic up to the order of each list)?
