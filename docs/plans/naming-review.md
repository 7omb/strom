# Review: terms and naming conventions

2026-11-14. Scope: every term of `GLOSSARY.md`, the naming conventions of `ARCHITECTURE.md` and the public names of the
user guide, read for understandability and consistency and against the words of the literature: arrows (Hughes,
`Control.Arrow`, cats), stream processing (StreamIt, Akka Streams, Flink, Beam, Rx, Hirzel et al.), queueing, executors
and structured concurrency. No finding renames a public name or re-proposes a rejected one: `where`, `loop`, `product`,
`route`, `Left`/`Right` and `Pools` are the user's choices (`docs/decisions/`). The names of the pinning pool were
reviewed apart: those not taken are in `docs/decisions/worker-pool.md`. Delete this file once its findings are done or
rejected (a rejection with its reason goes to `docs/decisions/`).

Suggested order: L1 to L3 with C1 (renames of private names, with `bin/rename.py`), then the texts (C2, C3, L4), then
the small ones; a session per group.

## L: Terms against the literature

**L1. "Element" is the literature's word for an item, and here it is three things.** The glossary's **element** is a
part of a stage (a step occurrence or a join, route, gather or loop; `start_tasks`, `_Element` in
`strom._interpreters.fusion`); the glossary's own **item** is "one element of a stream", as in Akka Streams, Beam and
Flink; and the pairs of `first`, `duplicate` and **lift** have elements too. Fix: the part of a stage is a **node** (a
vertex of the dataflow graph; `docs/decisions/sum-types.md` says so already): the glossary entry, `_Element` and its
variables, the docstrings, and `docs/decisions/tasks-of-an-element.md` with its name. "Element" stays for pairs.

**L2. "Reference semantics" is taken.** In the literature of programming languages it is the opposite of value semantics
(objects shared by reference), which the docstring of `duplicate` is about ("Both elements reference the SAME object").
What is meant has two established names, and the project uses both elsewhere: the **reference interpreter** (the
overview of `ARCHITECTURE.md`; Reynolds' definitional interpreter, WebAssembly's reference interpreter) and a stage's
**meaning** (Elliott's denotation: `helpers.meaning` in the tests, "Interpreters give that data its meaning").

- L2A: the glossary has **reference interpreter** (`run_reference`, public as `strom.testing.evaluate`) and **meaning**
  (a stage as a plain function, which runs must agree with, as a bag); the texts say "the reference interpreter" or "the
  reference" (as `check_against_reference` does), and `docs/decisions/reference-semantics.md` is renamed with it. The
  user guide changes in three sentences; no public name does.
- L2B: keep it: in its sentences it reads as "the semantics that is the reference".
- Recommendation: L2A.

**L3. `Expand` is the literature's flat map.** The leaves `Expand` and `AsyncExpand` (`strom._stages.model`) and their
builders (`expanding`, `async_expanding`, `_expanding_streamed`, `_expanding_listed`) map an input to 0..n outputs:
`flatMap` in Scala, Java, Rx, Flink, Spark and Kafka Streams, `FlatMap` in Beam (where `expand` is something else: the
definition of a composite transform), `concatMap` in Haskell; `docs/decisions/factories.md` itself says "flat_map
factories". Fix: `FlatMap`, `AsyncFlatMap`, `flat_mapping`, `async_flat_mapping`, `_flat_mapping_streamed` (and
`_flat_mapping_collected`, see C1), with the examples of the convention on leaf classes in `ARCHITECTURE.md`.

**L4. The user guide invites reading `loop` as ArrowLoop's.** Its correspondences give `product` as `***` and `route` as
`+++`; in that vocabulary `loop` is `ArrowLoop.loop`, the feedback of one element of a pair, which this `loop` is not.
The name stays (`docs/decisions/loop-name.md`). Fix: one sentence there: `loop` is iteration on the sum, as `tailRecM`
in cats (`Left`: again, `Right`: done) and `iterate` with a feedback stream in Flink, not `ArrowLoop.loop`.

**L5. A limit of a wait is a timeout.** `WAIT_LIMIT_TIME` and `RUN_LIMIT_TIME` (`tests/helpers.py`) follow the
convention for durations (`_time`), yet every call they go to names its parameter `timeout` (`Event.wait`,
`Future.result`, `asyncio.wait_for`), and the tools say `--timeout`. Fix: `WAIT_TIMEOUT`, `RUN_TIMEOUT`, and the
convention says so: a duration ends in `_time`, the limit of a wait is a `timeout`. `SATURATION_GRACE_TIME` stays.

**L6. The tests' `dup` is not the literature's.** `dup` is `a -> (a, a)`, the diagonal (Elliott's `dup`), which here is
`duplicate()`; `helpers.dup` emits its item twice, and the user guide and `strom.metrics` show it as the example of a
group ("dup | neg"). Fix: `twice`, also in those examples.

**L7. "Partition" belongs to the data in this domain** (Kafka, Flink, Spark: a shard of a stream). The glossary's
**partition** is the mathematical one, of a task's lifetime into idle, busy and blocked time. Fix: the word in front
that tells it apart, as the glossary does for the tools' terms: **lifetime partition**; the verb in
`docs/decisions/event-classes.md` stays.

## C: Consistency and understandability

**C1. `listed` in the names, "collected" in the texts.** `Offloader.listed`, `_expanding_listed` and the suffix
`_listed` of the conventions, against "collected in one pool task" (glossary, `docs/decisions/resources.md`) and
"cpu_stage collects all items" (user guide), beside `streamed`, which has one word. Fix: `collected` in the names.

**C2. "Placement" is used and not defined.** Where a function runs is the **resource** in the glossary (`"cpu"`, `"io"`,
or none) and the placement in `docs/decisions/factories.md`, `docs/decisions/stage-repr.md`, `strom._stages.display` and
the tests of the factories; the literature's term is placement (Hirzel et al.). Fix: a glossary entry, **placement**:
where a leaf's function runs, the event loop or the pool of a resource; the user guide's factory table is "by
placement". The heading "Resources vs. concurrency" of the user guide, which is about inputs, queues and pools, becomes
"Queues, pools and concurrency": a resource is `"cpu"` or `"io"` only.

**C3. The user guide never says what a step is.** It builds stages and then speaks of "the `concurrency` of a step",
event-loop steps, step occurrences and `StepId`; the difference between the two words is in the glossary only. Fix: one
sentence in the quick start: a step is a stage made by one factory from one function, the unit that has a `concurrency`,
a row in the statistics and a name in an error's note.

**C4. "Streaming" is the interpreter's word and the io pool's.** A "streaming run" is every run (the glossary's **run**
is by `stream`), while `streamed` and `StreamingBackend` are about items that come one by one. Fix: "run" for "streaming
run" where no contrast with the reference is meant, and the glossary's **streaming backend** says what streams: a
backend for streamed items, which keeps iterators in its workers and honours affinity.

## Checked, no finding

- Arrows: `first`, `second`, `fst`, `snd`, `swap`, `product` (`***`), `route` (`+++`), `left`, `right`, `Left` and
  `Right` (Either); `tag_by` sends true to `Left` as Hughes' `test` does; `loop` continues on `Left` as `tailRecM`.
- Structure: chain, join and loop are StreamIt's pipeline, splitjoin and feedbackloop; `route` is the router and
  `gather` the scatter-gather of the Enterprise Integration Patterns; `where` is LINQ's; stage (SEDA), step
  (scikit-learn's pipelines, Dataflow), fusion (Hirzel et al.), bag, backpressure, in flight, end of stream.
- Metrics: busy, idle, blocked (queueing networks with blocking), wait, utilization, wall and CPU time.
- Pools: pool, worker, task, backend (joblib), resource (the capacity kinds of Ray and Dask), affinity, pinned, offload,
  shutdown, shared memory, scope (structured concurrency), handle, opener.
- Tools: mutant, caught and missed (cargo-mutants), snapshot, diagnostic, revision.
