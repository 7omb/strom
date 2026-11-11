# Fusion

An optimisation pass (`fused`) before streaming runs, no new representation: consecutive event-loop steps become one
ordinary `Step` with an `AsyncExpand` leaf (the interpreters do not know about fusion); one loop over
`Stage[Never, object]` elements, so rebuilding takes the library's casts besides the iterator registry's one (checked by
the tests that fusion keeps the meaning); event-loop steps have no `buffer_size`: their queue holds twice the consumer's
concurrency, never less than the default `buffer_size`. Sandbox, 3 interleaved runs, ratio of µs per item: 1 / 3 / 6
event-loop steps 0.56 / 0.41 / 0.34, recorded 6 steps 0.21, `first(stage)` 0.67, fan-out 0.51; source alone, joins and
pool steps within noise

**Rejected**

- `buffer_size=0` as fusion switch (rendezvous is slower; ambiguous concurrency; mixes capacity and execution strategy)
- a fused leaf kind with member names, member positions and per-member error notes (fusion leaked into the
  representation and the interpreter)
- queue = 2 x consumer concurrency (a queue of 2 for single consumers: source alone 1.19 -> 3.60,
  `product(stage, stage)` 10.96 -> 19.37 µs per item)
- pulled steps (`_Pulled`: a second step engine, stretched `Receiver` meaning, broken `concurrency` meaning, joins
  1.06-1.14x slower)
- fusion inside the interpreter (not inspectable; one count per member in branches)
- a group stage kind (an arm in every dispatcher)
- units separate from stages (a shared loop slowed joins by about 1.6x)
- fusing into steps that wait (suffix: per-output cost for every step; prefix: serialises fan-out unless concurrency 1)
- a `_Group` record next to the single step (two representations of one value)
- a right-to-left fold with the fused form as data (`_Grouped`/`_GroupedThen`/`_Unfused`: 29 definitions) or as
  parameters of a typed recursion (22): no casts, but more and harder code than the loop (14)
- a typed zipper object (more variants)
- always fusing single steps (a generator per input)
- a synchronous group leaf (`Expand`: a group dropping many items would block the event loop)
