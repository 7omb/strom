# Benchmarks

The benchmarks are a full port to pytest-benchmark, which has the statistics the hand-rolled printer lacked. The cost
per step is derived from two rows (see `benchmarks/benchmark.py`), because a metric per step, t_n / n, charges the
source and the run to the steps (+54% for one step). The rounds of a benchmark run on one `asyncio.Runner` with its
pools opened on it, so that no round starts a loop.

A revision that a recorded measurement is against is a tag `baseline/<date>` (2026-11-11; the list:
`.claude/rules/benchmarks.md`), so that `bin/ab.py` can still run against it after the history was rewritten.

**Rejected**

- hybrid port (reason not recorded)
- citing a baseline by its commit hash (the history was squashed on 2026-11-10: the three commits the docs cited hung on
  the reflog only, which `git gc` prunes and no clone has)
- tags on those three commits (set and removed on 2026-11-11, the user's decision: they kept the squashed history, and
  `bin/ab.py` runs today's benchmarks on both sides, which import names those states lack)
- the date of a measurement in place of its revision, where the revision can be kept (a plan's step "reproduce" needs
  the code)
