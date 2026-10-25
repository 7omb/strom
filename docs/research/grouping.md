# Batching, group_by and key_by – strom

Research of 2026-11-08: how batching, grouping by key and partitioning by key could fit strom. Covers what other
libraries offer, the theory behind them, and designs with their fit. Follows gap 1 of `docs/research/features.md`.
Additions to the public API need the user's go-ahead. Claims about other libraries not checked against their sources are
marked [unverified].

## The central constraint

A stage maps ONE input to a bag of outputs, and a run's outputs are the union of those bags. Formally, a stage is a
homomorphism of bags (multisets): `f(A ⊎ B) = f(A) ⊎ f(B)`. This one property gives strom:

- order-free concurrency: any interleaving gives the same bag;
- the laws (`product`, `first`, `route`) and the reference semantics `strom.testing.evaluate`;
- lifting: a passed-through element or sequence number travels with each item, because each output belongs to exactly
  one input;
- per-input completion (`gather`, `loop`, and `ordered` and `with_completion` in `docs/research/ordering.md` and
  `docs/research/durability.md`).

Batching, `group_by` and `key_by` reach **across inputs**. Each design below is judged first by whether it keeps the
homomorphism. `docs/decisions.md` leaves folds across inputs open; `docs/todo.md` has a per-input `aggregate`.

The three words mean different things in other libraries:

| Term | Meaning | Changes what? |
| -- | -- | -- |
| batching | handle several items in one call (`executemany`, a bulk API, model inference, a chunk of pool tasks) | how items are executed; it may or may not change the meaning |
| `key_by` | partition a stream by key: the same key goes to the same worker and is handled in order (Flink, Kafka) | scheduling; also a prerequisite for keyed state |
| `group_by` | collect the items of each key into a group, or fold them (Beam `GroupByKey`, `CombinePerKey`; pandas, Polars) | meaning: an output depends on many inputs |

## Other libraries

**Batching**

- Akka/Pekko Streams:
  - `grouped(n)`, and `groupedWithin(n, d)` (a batch is emitted when full or after `d`);
  - `batch(max, seed, aggregate)` and `conflate`: aggregate *only while downstream backpressures*, so batches grow with
    load and shrink to one item when idle.
- Rx: `bufferCount`, `bufferTime`. aiostream: `chunks`. Python: `itertools.batched` (3.12).
- Beam:
  - `GroupIntoBatches` (per key, a batch size plus a maximum buffering duration);
  - `BatchElements` (batches of adaptive size that target a duration per batch \[unverified: parameter names
    `min_batch_size`, `max_batch_size`, `target_batch_duration_secs`\]).
- Ray Data: `map_batches(fn, batch_size=…)`, vectorised over pandas or Arrow batches. Ray Serve:
  `@serve.batch(max_batch_size, batch_wait_timeout_s)`. Callers send one request each; the decorator batches them and
  gives each caller its own result.
- Model servers: NVIDIA Triton's dynamic batching (preferred batch sizes, a maximum queue delay \[unverified: parameter
  names\]), TF Serving, TorchServe. Clipper (Crankshaw et al., NSDI 2017) adapts the batch size with AIMD (additive
  increase, multiplicative decrease) under a latency target.
- Kafka producer: `batch.size` and `linger.ms`. Databases: group commit. Martin Thompson's "smart batching" (2011): take
  whatever has queued up while the previous batch ran; no timer.
- `multiprocessing.Pool.map(chunksize=…)`, `concurrent.futures` `Executor.map(chunksize=…)` for processes.

**Partitioning and keyed state**

- Flink: `keyBy` partitions by key hash. `KeyedProcessFunction` and `ValueState` give state per key, and order per key
  holds within a partition.
- Kafka: partitions by key; one consumer per partition gives order and affinity per key. The Confluent Parallel Consumer
  adds "key order" mode: in parallel, but never two records of one key at once.
- Bytewax: `key_on`, then `stateful_map(state, value) -> (state, out)`, `fold_window`, `reduce_final`, `collect` (a
  batch per key with a timeout) [unverified: the current operator names].
- Akka: `groupBy(maxSubstreams, key)` makes substreams per key; `mapAsyncPartitioned` gives order per key.
- Actor systems (Orleans grains, Akka cluster sharding): one actor per key handles its messages one at a time.

**Grouping**

- Beam: `GroupByKey` (per window), `CombinePerKey(CombineFn)`. A `CombineFn` has `create_accumulator`, `add_input`,
  `merge_accumulators` and `extract_output`.
- Spark: `groupByKey` vs `reduceByKey`. The latter combines before the shuffle and is the one to recommend.
- Flink: `AggregateFunction` on windows (tumbling, sliding, session), event time with watermarks.
- `itertools.groupby` groups only *consecutive* items, so it needs order. pandas and Polars group a whole frame.

## Theory

- **Homomorphisms.** A per-input stage is `concatMap`: a list homomorphism, and a bag homomorphism when order is ignored
  (Bird-Meertens formalism; the third homomorphism theorem, Gibbons 1996). Homomorphisms parallelise without
  coordination, which is why strom's runs need none.
- **Aggregation as a monoid.** Folding a bag gives the same result for every order and split exactly when the fold is a
  *commutative monoid* (an associative, commutative `merge` with a neutral element), applied as a homomorphism from bags
  into it. This is why MapReduce combiners, Beam's `CombineFn`, Spark's `reduceByKey` and Flink's `AggregateFunction`
  ask for associativity (Beam also for commutativity). `group_by` with a combiner is a homomorphism into *maps of
  monoids*, merged key by key. So it is deterministic over a bag, but only at the end of a finite stream, or per window.
  The same idea underlies CRDTs (state-based: a join semilattice) and Gonzalez's `foldl` library (folds as an
  `Applicative`: several folds in one pass).
- **Grouping without a combiner** (`GroupByKey` emitting each group) is also deterministic as a bag of groups, if each
  group is itself a bag. It needs memory for every item until the end.
- **Batching by count or time is not deterministic.** Which items share a batch depends on timing. Its meaning is "some
  partition of the inputs into blocks of at most n". A test can check invariants (each item in exactly one batch, sizes
  ≤ n), not equality with the reference. The Dataflow model (Akidau et al., VLDB 2015) treats processing-time triggers
  as nondeterministic for the same reason.
- **Batching aligned per item keeps the homomorphism.** If `fn(batch)[i]` equals `fn([batch[i]])[0]` (*batch
  invariance*), batching is only an execution strategy, as in Ray Serve's batching. The meaning is the call per item, so
  the reference semantics and the laws stay as they are. Batch invariance is a contract on the user's function, like
  purity.
- **Keyed state is a Mealy machine per key** (`S × I → S × [O]`; `scan`; arrow-based stream transducers,
  `ArrowCircuit`). Its outputs depend on the order of the inputs per key. It is deterministic only if that order is
  fixed, which needs order per key (`ordered(f, key=…)`, `docs/research/ordering.md`). It also breaks strom's laws:
  `product(f, g)` calls g once per input, while `first(f) | second(g)` calls it once per output of f. A stateful g sees
  different sequences, so the two sides differ. This is the same reason `docs/decisions.md` (Law rewrites) needs an
  effect marker before rewrites that change calls.
- **Latency vs. throughput.** By Little's law, batching raises latency by the time an item waits for its batch. Timers
  bound that wait. Smart batching makes it zero at low load: a batch is what has queued up while the previous one ran,
  so it adapts to load with no tuning. AIMD (Clipper) and target durations (Beam's `BatchElements`) adapt the size to a
  latency target.

## Designs

### A. Inside the per-input model (keeps every law)

**A1. Batched functions, aligned per item (dynamic batching).**

```
batched(fn, *, max_size, max_wait=None) -> Batched[I, O]
fn: Callable[[Sequence[I]], Sequence[Iterable[O]]]   # one iterable of outputs per item, in order
io_stage(batched(insert_rows, max_size=500), concurrency=2)
cpu_stage(batched(predict, max_size=32, max_wait=0.005))
io_stage(using(db, batched(insert_rows, max_size=500)))   # or batched(using(...)), see below
```

- **Meaning:** `Batched` is an ordinary function of one input: `fn([item])[0]`. This follows the precedent of `using`
  (`Using`). The reference semantics, the event loop, fusion and lifting run it unchanged, per item.
- **Streaming runs** recognise it in the step's task loop:
  - the loop awaits the first item;
  - it takes more with `get_nowait` up to `max_size` (smart batching: no timer, batches grow under load);
  - only if `max_wait` is set does it wait up to that long for more, with `asyncio.timeout`;
  - it calls `fn` on the batch in one pool task (like `cpu_stage`'s `listed`);
  - it merges each element's outputs with that element's kept value. The `Focus` applies per element, so
    `first(io_stage(batched(...)))` and `product` branches work, with counting per element.
- `concurrency` is the number of batches in flight.
- **Value check:** `len(fn(batch)) == len(batch)`, a value constraint types can't express (allowed by `ARCHITECTURE.md`,
  Conventions).
- **Errors:** an error fails the whole batch, and the run fails fast anyway. The stage note is as usual. The error can't
  name one input; it could note the batch size.
- **Effects:**
  - `executemany` with a transaction per batch;
  - outputs after the commit, so the per-input transaction advice in the user guide becomes a per-batch one;
  - durability (`docs/research/durability.md`) then commits per batch, and the input keys of a batch are known.
- **Queue sizing:** the input queue of a batched step must hold at least `concurrency × max_size` items, or batches
  never fill. Today, `_intake` returns the first step's `concurrency` to size the queue before it.
- **Metrics:** `InputHandled` per input stays meaningful (wait, busy, blocked are shared by the batch). Possible
  additions: a field or event with the batch size, and a `diagnose` hint about batches that stay small.
- **Chunked pool tasks** (`docs/todo.md`, Performance: process-pool chunks measured 117 → 1.8 µs per item) are the
  special case where `fn` maps a per-item function over the batch. A library helper `chunked(fn, size)` gives that
  without writing a batch function (a lambda wouldn't pickle for processes).
- **Typing:** `batched` is generic in `I` and `O` and returns `Callable[[I], Iterable[O]]`, so every factory accepts it
  without overloads. `docs/decisions.md` (Worker handles) rejected a keyword that changes `fn`'s arity; this design
  avoids that. With handles, `using(db, batched(f))` gives `f` the handle per batch only if `using` passes it into the
  batched function. The order of wrapping needs a decision.
- **Where batching is pointless:** event-loop `stage(batched(...))`, since a cheap synchronous function gains nothing.
  It could raise when built, or just run per item. `async_stage` makes sense: an async bulk API.

Fit: very good. It keeps the meaning, adds no stage kind and no leaf arm, and costs nothing when off (the step loop
checks once per step whether its function is a `Batched`).

**A2. Keyed concurrency (`key=` on steps).**

```
io_stage(update_account, concurrency=8, key=lambda e: e.account_id)
```

- At most one item per key in flight in that step. Items of other keys pass a waiting one, as in the Parallel Consumer's
  key order or an actor per key.
- Prevents races on the same row or entity without a lock in user code.
- It is scheduling only, so the bag and the laws are unchanged.
- **Implementation:** a dict of busy keys and a waiting queue per key in the step. Choose: a task whose input's key is
  busy parks it and takes the next input, or it waits (simpler, but it blocks the task). Parking needs a limit, or one
  hot key fills memory.
- **Affinity** (the same key always on the same worker process, for caches in worker handles) would need routing by key.
  `StreamingBackend` routes calls to a worker already (`affinity`, used for `io_stage` iterators); `Processes` for "cpu"
  does not. Leave affinity out until a case needs it.

Fit: good. It is a parameter on steps, the reference semantics is unaffected, and it combines with `ordered(f, key=…)`
for order per key.

**A3. Per-input folds (`aggregate`, `docs/todo.md`).** `gather(f) | stage(fold)` without keeping the list: fold the
outputs of each input as they come. A per-input `group_by` is `aggregate(f, group_fold)` (or `gather(f) | stage(group)`
today), deterministic as a bag of groups. Fit: very good; it reuses `gather`'s machinery.

### B. At the boundary of a run (no change to the model)

**B1. Batching inputs before the run and outputs after it.** A run's inputs may be an async iterable, and its outputs
are one. Async helpers like `aiostream.chunks` or a `batched(aiterable, n, max_wait)` async generator turn a stream into
a stream of lists:

```
stream(io_stage(insert_rows_batch) | flatten(), batched_inputs(rows, 500, max_wait=0.1), pools)
```

Each batch is one input, so the per-input meaning holds for batches. This is the documented workaround ("the stream as
one input") in a better form: it streams, and memory is bounded. Fit: good. It is consumer or caller code, as the
decisions on inputs and folds say. The library could ship the helper, or an example only.

**B2. Grouping a whole run (`group_by` with a combiner) as consumer code.** A fold of the outputs into a `dict` of
monoids, at the end. Already possible; an example with a `CombineFn`-like protocol would show the pattern. A library
`Fold` type (`foldl`-style, composable) is possible but adds public API for what a loop does.

### C. Across inputs inside stages (changes the model)

**C1. A batching stage `batch(n, max_wait): Stage[I, list[I]]`.**

- Its outputs belong to no single input, so a batch can't carry one sequence number or kept value.
- `first(batch(n))` has nothing to do with `x`. It can't be lifted, it can't sit in a `product` branch or a `gather` or
  `loop` body, and the reference semantics would have to pick one partition.
- It would need a second category of stages (stream transducers, `Stream[I] -> Stream[O]`) with its own composition
  rules, allowed only at the top level of a run. That is two kinds of stage in the type system, and B1 gives the same
  result at the boundary.
- Not recommended. A1 covers the uses of batching (bulk calls), and B1 covers batches as values.

**C2. Keyed state (`key_by | stateful_map`, Bytewax/Flink style).**

- Deterministic only with order per key (`ordered(f, key=…)` first).
- Breaks the laws (above), so it needs an effect marker.
- Needs durable state for recovery: barrier snapshots (`docs/research/durability.md`, Level 4).
- Not recommended now. If it comes, it should come together with order per key, the effect marker and the durability
  levels, as one design.

**C3. Windows (tumbling, sliding, session; event time, watermarks).** Builds on C2 plus timers and watermarks: the core
of Flink, Beam and Bytewax, and a different library. Out of scope.

## Summary

| Design | Keeps laws and reference | New public API | Covers |
| -- | -- | -- | -- |
| A1 `batched(fn, max_size, max_wait)` | yes (batch invariance is the user's contract) | `batched`, `Batched` (maybe `chunked`) | bulk DB writes, bulk APIs, model inference, chunked pool tasks |
| A2 `key=` on steps | yes | one parameter | no concurrent work on one entity |
| A3 `aggregate(f, fold)` | yes | one combinator (already in `docs/todo.md`) | group or fold per input |
| B1 batch inputs or outputs at the boundary | yes | none, or a helper | batches as values |
| B2 fold a whole run in the consumer | yes | none (example) | `group_by` over a finite run |
| C1 `batch` as a stage | no (not liftable) | a second stage category | — (A1 and B1 instead) |
| C2 keyed state | no (order-dependent, breaks `product`) | several | stateful stream processing |
| C3 windows | no | many | event-time analytics |

## Recommendation

1. **A1 dynamic batching via `batched`.** Use smart batching by default (no timer) and an optional `max_wait`. It solves
   the most common production need (bulk writes, inference) without touching the semantics, and subsumes chunked pool
   tasks. Measure it against `cpu_stage`/`io_stage` per item and against B1.
2. **A2 keyed concurrency** together with `ordered(f, key=…)`: both are "per key" scheduling and could share the key
   handling.
3. **A3 `aggregate`** as planned; group per input with it.
4. **B1 and B2** as documented patterns or examples. Folds across a run stay consumer code, as decided.
5. **C1 to C3 rejected for now**, with the reasons above (record them in `docs/decisions.md` if the user agrees).

## Open questions

- Name: `batched` collides in spirit with `itertools.batched`, which gives batches as values (B1). Alternatives:
  `in_batches`, `bulk`, `vectorized`.
- How `batched` and `using` nest: does the handle go to the batched function once per batch (`using(db, batched(f))`)?
  Which order reads naturally?
- Should A1 offer adaptive sizing (AIMD or a target duration per batch), or is smart batching plus `max_size` enough?
  Measure.
- For A2: does a task with a busy key park the input or wait? How many parked inputs are allowed?
