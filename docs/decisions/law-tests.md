# Law tests

Each law has its own test, not one test per family, so that a failure names the law and no single test bounds the
suite's wall time. The test of a family took 10.2 s. The `*_law_sides` functions return the sides by law name, and the
tests are parametrised by those names (taken from the dict, so each law is named once). Each example opens its own
`Pools`. The suite got faster for about 35% more CPU time.

**Measured** (20 cores, 2026-11-04)

| Run | Before | After |
| -- | -- | -- |
| `make test` | 10.7 s | 4.8–7.7 s |
| the run-law tests, serial | 17–29 s | 29–37 s |

**Rejected**

- a module-scoped `Pools` for all examples (27–33 s, one run 103 s: the pool tasks of a failed example finish and occupy
  the pool for the next)
