# Features compared with other data processing libraries – strom

Research of 2026-11-08: what strom has and lacks compared with production data processing libraries. Compared with
in-process Python libraries (pypeln, mpire, aiostream, streamz), stream processors (Bytewax, Faust, Flink, Beam), batch
engines (Ray Data, Dask), and stream libraries of other languages (Akka/Pekko Streams, Reactor/Rx, Haskell
conduit/streamly). Gaps that `docs/decisions/` rejects on purpose are marked *rejected*. Gaps already in `docs/todo.md`
are marked *todo*. Decisions taken from this go to `docs/decisions/`, tasks to `docs/todo.md`.

## Strengths

- Typed composition with laws: stages are data, `|` is Kleisli composition, `product` and `route` are the arrow
  combinators `***` and `+++`; the laws are property-tested, and streaming runs are checked against a sequential
  reference semantics (`strom.testing.evaluate`). Rare outside Haskell.
- Shared, bounded pools: one "io" and one "cpu" pool for all stages and runs of a `Pools`, and a step occupies pool
  capacity only while it holds an item. pypeln and mpire give each stage its own workers, so total resource use is
  unbounded.
- Backpressure end to end, also inside `product` and `route` branches and the feedback of `loop`; no deadlocks between
  steps (`ARCHITECTURE.md`, Concurrency and pools).
- Structured failures: fail-fast, ONE `ExceptionGroup` (`RunFailed`) with a stage note per error, generators closed on
  the worker that made them, pool tasks of a failed run skipped where possible.
- Worker handles (setup and teardown per process, like Beam's `DoFn.setup` and Pekko's `mapWithResource`), a fusion
  pass, and metrics as an event stream with `StatsRecorder` and `diagnose`.

## Gaps

Ordered by how often they would block a real use.

### 1. State across inputs

A stage maps one input to a bag of outputs; `gather` collects only within one input, and folds across inputs are open
(*todo*: `aggregate`). Missing:

- Batching, `groupedWithin(n, t)` (Akka; aiostream's `chunks`; Ray's `map_batches`): the usual way to use `executemany`,
  bulk HTTP APIs and batched model inference. Today the stream must become one input (a stage making the items, run on
  `[None]`).
- Keyed state and `group_by`/`key_by` (Beam, Flink, Bytewax's `stateful_map`), deduplication (`distinct`), `scan`,
  aggregation per key.
- Windows (tumbling, sliding, session), event time, watermarks and late data (Flink, Beam, Bytewax).
- Joins of two streams; sorting and top-k.

### 2. Ordered outputs

Outputs are always a bag. Akka offers `mapAsync` (ordered) next to `mapAsyncUnordered`; pypeln, mpire's `imap` and Ray
Data's `preserve_order` give the same choice. ETL jobs often need input order (logs, sorted files, results by row
number) or an order per key. `product` already matches results by sequence numbers (`lift_sequenced`): an opt-in reorder
buffer per run or per step could build on it. No decision rejects it.

### 3. Error policies beyond fail-fast

Only Akka's "Stop" exists. Missing:

- Retry with backoff and "resume" (skip an item, or send it to a dead-letter output) (*todo*).
- Timeouts per item and deadlines per run: a hanging `io_stage` call holds a pool thread forever. Only a deadline under
  cooperative cancellation is in `docs/todo.md`.
- Interrupting running work after a failure: threads can't be interrupted; on processes up to `cpu_workers + 1`
  dispatched pool tasks still run (*todo*: cooperative cancellation).
- The failing input on the error: errors carry a stage note, not the input item, which a dead-letter output or debugging
  needs.

### 4. Throughput controls

- Rate limiting, `throttle` (Akka, aiolimiter), for APIs with quotas: `concurrency` bounds items in flight, not a rate.
- Cross-stage and weighted limits, adaptive concurrency (*todo*).
- Batched pool tasks: one pool task per item; process-pool `executor.map` with chunks of 100 measured 117 -> 1.8 µs per
  item (*todo*). mpire and `multiprocessing` expose `chunksize`.
- Columnar and zero-copy data paths: items move one by one, pickled to processes; no Arrow or record batches, no
  shared-memory arrays. Ray Data, Polars' streaming engine and DuckDB win by orders of magnitude on tabular data. A
  scope question, but the main reason strom would lose on data-heavy work.
- Memory limits in bytes, spilling to disk: queues are bounded by item counts only.

### 5. Topology

- Several sources, merging or zipping independent streams, broadcasting to several sinks (Akka's GraphDSL, Rx's
  `merge`/`zip`, Beam's multiple outputs): graphs are linear plus bounded joins. *Rejected*: sinks, source factories and
  `fanout` (`&&&`); effects are the consumer's code or effect stages.
- Partitioning by key across workers (order per key, affinity for state).

### 6. Durability and delivery guarantees

No checkpointing, no recovery after a crash, no documented at-least-once or exactly-once contract (Flink, Bytewax, Beam,
Faust, Kafka Streams). When the process dies, the items in flight are lost and the caller doesn't know which inputs were
done. A state backend is out of scope for an in-process library; documented guarantees and a way to learn which inputs
completed (to resume a run) are not.

### 7. Connectors and distribution

- No connectors (Kafka, files and object stores with Parquet or CSV, databases, queues), by the no-dependency policy;
  Beam, Bytewax and Ray ship them. Usual answer: optional extras or a companion package.
- Several hosts only through a backend of one's own (`strom.backends`); no example (*todo*), no autoscaling, no data
  locality. `FromExecutor` with Dask or loky is untested against the real libraries (*todo*).

### 8. Operations

- OpenTelemetry export, queue fill, event-loop lag, histograms (*todo*); a live progress view (mpire's and tqdm-style
  progress bars). The event model is ready for them.
- Graceful drain: on SIGTERM stop taking inputs and finish the items in flight within a deadline. Leaving the block of
  `stream` cancels the run.
- `contextvars` in thread-pool tasks (*todo*): request ids and trace context are lost in `io_stage`.
- Changing settings (such as `concurrency`) of a running, long-lived run.

### 9. Ergonomics and reach

- Async only. pypeln, mpire and Dask have a sync API. *Rejected* (a loop driven from sync code costs a resume per item,
  or a thread changes where event-loop functions run); still the largest hurdle for scripts and notebooks.
- Process backend: functions must be top-level and picklable; no cloudpickle or dill option (mpire, Ray), so lambdas and
  closures fail there.
- Platforms: Python 3.14+ only; worker handles on processes use `SIGUSR1` (POSIX only, no Windows).
- Maturity: no release on PyPI, no versioning or stability policy, no docs site beyond the package docstring.

## Summary

| Area | strom | Typical production library |
| -- | -- | -- |
| Composition, typing, laws, testability | ahead | weak |
| Backpressure, shared pools, structured failures | on par or ahead | varies |
| Batching, windows, keyed state, stream joins | missing | core feature |
| Ordered outputs as an option | missing | standard |
| Retry, timeouts, dead letters | missing (retry and resume: *todo*) | standard |
| Rate limiting, batched pool tasks | missing (batched pool tasks: *todo*) | common |
| Checkpointing, delivery guarantees | missing | stream processors have it |
| Connectors, distribution | none; backends of one's own | extensive |
| Export of metrics | events and statistics; OpenTelemetry *todo* | OpenTelemetry, UIs |

The three gaps that block the most uses: batching across inputs, timeouts with retry and resume, and ordered outputs.
All three fit the design (batching as a stage kind, retry on top of `loop`, order on the sequence numbers `product`
uses). Durability and connectors are scope decisions.

Not yet in `docs/todo.md`: timeouts, ordered outputs, rate limiting, the failing input on errors, graceful drain.
