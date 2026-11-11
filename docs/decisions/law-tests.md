# Law tests

One test per law: the `*_law_sides` functions return the sides by law name, the tests are parametrised by those names
(taken from the dict, so each law is named once); per-example `Pools`; `make test` 10.7 -> 4.8–7.7 s (20 cores,
2026-11-04) for about 35% more CPU (run-law tests serial 17–29 -> 29–37 s)

**Rejected**

- one test per family looping over its laws (its 10.2 s test bounded the suite's wall time; a failure did not name the
  law)
- a module-scoped `Pools` for all examples (27–33 s, one run 103 s; see `pool-tasks-of-a-failed-run.md`)
