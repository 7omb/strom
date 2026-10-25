# Durability and checkpointing – strom

Research of 2026-11-08 on durability and checkpointing: what the methods offer, how they are implemented, how well they
fit strom, and their theoretical basis. Follows gap 6 of `docs/research/features.md`. Additions to the public API need
the user's go-ahead. Claims not checked against their sources are marked [unverified].

## Where strom stands

- A run keeps nothing outside its process. When the process dies, the items in flight are lost, and the caller doesn't
  know which inputs were done.
- Pool tasks run at most once: a backend never retries (user guide, Failures). The first failure stops the run
  (fail-fast).
- The inputs belong to the caller (no sources, `docs/decisions.md`, Factories and Runners). The outputs are a bag
  delivered to the consumer's code, which does the effects.

Between runs, strom offers **at-most-once** per output and no recovery.

## Theory

### Rollback recovery

The standard survey is Elnozahy, Alvisi, Wang and Johnson, "A Survey of Rollback-Recovery Protocols in Message-Passing
Systems" (ACM Computing Surveys, 2002). It sorts the methods into two families.

- **Checkpoint-based recovery** restores a saved state.
  - *Uncoordinated* checkpoints can cascade into the domino effect: rolling back one process invalidates messages that
    others received, and so on.
  - *Coordinated* checkpoints form a consistent global state.
  - *Communication-induced* checkpoints are forced by piggybacked information.
- **Log-based recovery** replays logged nondeterministic events from a checkpoint, under the *piecewise deterministic*
  (PWD) assumption: between two nondeterministic events (a message receipt, a clock reading), a process is
  deterministic.
  - *Pessimistic* logging writes each event before acting on it.
  - *Optimistic* logging writes asynchronously and may lose recent events.
  - *Causal* logging piggybacks the logged events on messages.
- **The output commit problem.** The outside world can't be rolled back, so a system must not release an output until
  the state that produced it is recoverable. For strom, the consumer's code is that outside world: every effect there is
  an output commit.

### Consistent snapshots

- **Chandy and Lamport**, "Distributed Snapshots: Determining Global States of Distributed Systems" (ACM TOCS, 1985).
  Markers are sent along FIFO channels. A process records its state on the first marker and records each channel until
  that channel's marker arrives. The result is a consistent cut in Lamport's happens-before order (1978): no message
  received without being sent.
- **Asynchronous barrier snapshots** (ABS; Carbone, Fóra, Ewen, Haridi, Tzoumas, "Lightweight Asynchronous Snapshots for
  Distributed Dataflows", 2015) are Flink's variant for dataflows. Barriers flow with the data. An operator with several
  inputs *aligns* them (it blocks an input once that input's barrier has arrived) and then snapshots its state. In a
  DAG, no channel state is stored. In cycles, only the records on back edges are logged. *Unaligned* checkpoints (Flink
  1.11) store the in-flight data instead of blocking, which trades storage for latency under backpressure. State
  management is in Carbone et al., "State Management in Apache Flink" (VLDB 2017).

### Exactly-once

- Exactly-once *delivery* over a lossy channel is impossible (the two generals problem). Systems give exactly-once
  *effects*: at-least-once delivery plus idempotent or deduplicated effects, often called "effectively-once".
- The end-to-end recipe (Flink, Kafka Streams, Spark):
  - a **replayable source** with positions (offsets),
  - a **consistent snapshot** of state together with the source positions,
  - a **transactional or idempotent sink**: two-phase commit on the checkpoint (Flink's `TwoPhaseCommitSinkFunction`),
    or writes keyed for upsert.
- **MillWheel** (Akidau et al., VLDB 2013): each record has an id; state and the records it produces are written
  atomically per key ("strong productions"), and receivers deduplicate by record id.
- **Discretized streams** (Spark Streaming; Zaharia et al., SOSP 2013): micro-batches of deterministic tasks, recovered
  by recomputing from lineage instead of by replication.
- **Kafka Streams** (Wang et al., "Consistency and Completeness: Rethinking Distributed Stream Processing in Apache
  Kafka", SIGMOD 2021): consume, transform and produce in one Kafka transaction, which also commits the input offsets.
- **Beam** (the Dataflow model, Akidau et al., VLDB 2015): a runner may retry *bundles*, so a `DoFn` must tolerate
  re-execution. Dataflow deduplicates at shuffles.

### Durable execution

- Temporal, Restate and DBOS journal each step's result (an event-sourced history) and replay deterministic workflow
  code, skipping steps that already have a result. This is log-based recovery with pessimistic logging at step
  granularity.
- Prefect's result persistence and caching keys and Dagster's asset materialisations apply the same idea per task
  [Prefect details unverified].

### Acknowledged queues

- Celery's `acks_late`, SQS visibility timeouts and Kafka consumer offsets give at-least-once per message: a message is
  acknowledged after processing and redelivered if no acknowledgement arrives.
- Parallel processing completes out of order, so a plain offset (a low watermark) holds back completed work. The
  Confluent Parallel Consumer commits the low watermark plus an encoded set of the offsets completed above it \[encoding
  details unverified\].

## What the methods offer

| Method | Guarantee | Needs | Cost while running |
| -- | -- | -- | -- |
| Nothing (strom today) | at-most-once | — | none |
| Progress tracking: completed inputs persisted | at-least-once per input, effectively-once with idempotent or transactional effects | identifiable or replayable inputs, a store, a completion signal per input | a write per input (or per batch of inputs) |
| Result journaling per step (durable execution) | crash recovery inside an input; finished pool tasks are not redone | deterministic stage, picklable results, keys per (step, item) | a write per item and step |
| Operator-state snapshots (ABS, Chandy-Lamport) | consistent state across inputs | state across inputs, barriers in every queue, a snapshot store | barrier alignment, state serialisation |
| Transactional sinks (two-phase commit) | exactly-once effects on the sink | a transactional target, commits tied to checkpoints | latency of the commit interval |
| Lineage recomputation (D-Streams) | recomputation of lost results | deterministic tasks, immutable partitioned inputs | none until a failure |

## The key fact for strom: no state across inputs

Every stage maps **one** input to a bag of outputs. `gather`, `loop` and `product` keep state only per input, and only
while that input is in flight. The state of a run that matters for recovery is therefore only **the set of inputs whose
outputs have all been committed**. Nothing else needs a snapshot: an unfinished input is redone from scratch. Bag
semantics helps too. Redoing inputs in another order changes nothing, so the PWD assumption only has to hold per input,
and only if journaling is used.

This puts strom close to an acknowledged queue (per-input at-least-once). It needs neither Chandy-Lamport nor ABS. That
changes when strom gains state across inputs (batching, keyed state, windows: gap 1 of `docs/research/features.md`).
Operator state then needs barrier snapshots. strom's graphs are linear plus bounded joins and the `loop` feedback, so
the aligned ABS variant applies, with logging of the items on the back edge for `loop`, as the ABS paper does for
cycles.

## Levels of support

### Level 0: documented guarantees

State it in the user guide: at-most-once, nothing persisted, an in-flight input lost on a crash. Free, and needed for
every later level.

### Level 1: a completion signal per input, plus a pattern

What's missing for users to build effectively-once themselves is knowing **when all outputs of an input have been
delivered**. strom tracks this already for `gather` and `loop` (`_InFlight` and `lift_sequenced` in
`src/strom/_interpreters/streaming.py`).

- **Possible today with `gather`.** `gather(f)` emits one list per input once the input is complete. A consumer writes
  the list and the input's key in **one transaction**, which commits outputs and progress atomically (the transactional
  outbox pattern; MillWheel's strong productions in miniature). On restart, a `where(lambda x: key(x) not in done)` in
  front of the stage skips the finished inputs. Effects are exactly-once per input, with no new API. Limit: the whole
  list of an input stays in memory.
- **A streaming completion marker.** A combinator that tags outputs and marks the end of each input:
  ```
  with_completion(f): Stage[I, Left[O] | Right[I]]   # Left(out) for each output, then Right(input)
  ```
  This is the same machinery as `gather`: the body counts per input, and the marker follows the input's last output in
  the output stream, because the one loop that puts the outputs puts the marker after them. The consumer commits its
  effects, and when it sees `Right(x)`, records `x` as done, in the same transaction or after the effects (at-least-once
  for a partly committed input). It shares the kind and the interpreter with `ordered` (`docs/research/ordering.md`):
  both are "a body plus completion per input" with different emitting policies. Reference semantics: the outputs of an
  input, then its marker. Bag laws still hold for the `Left` part.

Fit: very good. No dependencies, no store in the library, no new concept in the runtime. It follows the decisions that
inputs belong to the caller and effects are the consumer's code.

### Level 2: a progress store as a run option

```
stream(stage, inputs, pools, progress=Progress(store, key=lambda x: x.id))
```

- The run skips inputs that `store` marks done. It marks an input done once all its outputs were *acknowledged* by the
  consumer.
- **Acknowledgement is the difficult part.** An async iterator can't tell when the consumer has finished its effect on
  an output. Asking for the next output is a weak implicit acknowledgement, since several consumers can share `outputs`.
  An explicit one means outputs carry a handle (`out.ack()`) or keys, which is a different output type and a second API.
- **Store.** A small `Protocol` (`load() -> done keys`, `mark(keys)`) with an optional `sqlite3` implementation from the
  standard library. Batched marks (a commit interval) trade write cost for redone work.
- **Keys or positions.** Positions (the input's index) need inputs that replay deterministically (a file, a sorted
  query). Keys need a `key` function. For a long run, the set of done keys is best stored as a low watermark plus the
  exceptions above it, as the Parallel Consumer does.

Fit: medium. It is a second way into a run's guarantees, Level 1 covers it with user code, and the acknowledgement
problem has no clean answer for a shared async iterator. Only if Level 1 proves too low-level in practice.

### Level 3: result journaling per step (durable execution)

- Memoise each pool task's result under (step name, input key) in a durable store. On replay, a task with a stored
  result returns it without running.
- This helps when a single input is expensive: a model call, a long pagination in `loop` (journal the `Left` items, the
  next page, and resume mid-input).
- **Implementation.** Possible *without changing strom*, as a `Backend` wrapper (`strom.backends`) whose `run` looks up
  and stores results; or as a function wrapper used like `using`. Keys must be deterministic and stable across runs (the
  function's qualified name plus a stable hash of the arguments). Results must pickle. `io_stage` streams items one by
  one, so it would journal the iterator's items one at a time and replay them, which only works for deterministic
  iterators.
- **Costs.** A write per item and step. Determinism and versioning trouble arrive as soon as the stage's code changes
  between the crash and the replay. Temporal solves that with workflow versioning, a whole subsystem.

Fit: as an optional wrapper outside the core, fair. In the core, poor: it touches every pool task, and an optional
feature must cost nothing when off (`ARCHITECTURE.md`, Conventions).

### Level 4: operator-state snapshots (ABS)

Only meaningful once there is state across inputs. Then:

- barriers are put into the input queue at a checkpoint interval and flow through every step;
- joins (`product`'s split and merge loops) align barriers per branch;
- `loop` logs feedback items between the barrier and its return, as the ABS paper does for back edges;
- each stateful stage snapshots its state to a store;
- the snapshot is complete when the barrier reaches the consumer, which commits its effects for that epoch (two-phase
  commit with the consumer).

Barriers would be a new item kind in every queue and every step loop, which costs every item even with checkpointing
off. A separate loop variant would avoid that, which `docs/decisions.md` (Metrics check) rejected for recording. Fit:
poor for now, and premature without stateful stages.

### Level 5: distributed exactly-once with transactional sinks

Kafka transactions, two-phase-commit sinks, deduplication in the shuffle: out of scope for an in-process library without
connectors.

## Recommendation

1. Level 0 now: document the guarantees.
2. Level 1: write the `gather` pattern into the user guide (or as an example with `sqlite3`: outputs and the input's key
   in one transaction, `where` skipping done inputs on restart). It shows effectively-once with today's API. Then decide
   on `with_completion` together with `ordered`, since both reuse the same per-input completion machinery and could
   share a stage kind.
3. Level 3 as an example backend wrapper if a user needs recovery inside an input. Keep it out of the core.
4. Revisit Level 4 only together with stateful stages (batching, keyed state).

## Open questions

- One kind for "body plus completion per input" with policies (collect: `gather`; stream in order: `ordered`; stream
  with markers: `with_completion`), or separate kinds?
- Does `with_completion` belong in the library, or is `gather` plus an example enough?
- How do worker crashes inside a run relate (a retry policy, gap 3 of `docs/research/features.md`)? They are recovery
  inside a run, while this document covers recovery across runs. The two share the requirement of idempotent effects.
