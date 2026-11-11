# Test tools for users

`strom.testing` (2026-11-05): `evaluate`/`evaluate_async` (the reference semantics, public), `bag` (outputs as a
multiset by `repr`: unhashable items work, a failing assert shows the difference), `check_against_reference`
(2026-11-06; raises `AssertionError` naming the missing and extra items, like the backend checks);
`strom.testing.__all__` lists exactly these and the backend checks (pydoc and star imports showed its imports);
`RunFailed`, the `ExceptionGroup` subclass a failed run raises (`derive` keeps it through `except*`; a plain
`BaseExceptionGroup` only if an error is no `Exception`); `RunStats.step(name)` (raises on a name of several
occurrences); plumbing stages `swap`, `fst`, `snd`, `untag` (event-loop, 1:1). `bag` and `check_against_reference`
compare each item as a whole: the list of a `gather`, which comes in no particular order, is sorted by a stage after the
gather, as the docstrings of `gather`, `bag` and `check_against_reference` say (2026-11-11: the check failed on a
correct `gather` with a concurrent body)

**Rejected**

- a pytest plugin or fixtures (a dependency)
- a `key` parameter for `bag` and `check_against_reference`, to compare such lists (a public addition for what a stage
  in the pipeline under test does)
- a lambda as the sorting stage in the docs (pyright does not infer its parameter: a named function)
- `same_bag(a, b) -> bool` and `agrees_with_reference -> bool` (no difference shown)
- the message string as the only mark of a run's group (the tests imported the private constant)
- `ManualClock` (2026-11-07: the run's clocks are fixed, see `recorder.md`)
