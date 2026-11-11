# Benchmarks

Full pytest-benchmark port; cost per step derived from two rows (see `benchmarks/benchmark.py`); the rounds of a
benchmark run on one `asyncio.Runner` with its pools opened on it (2026-11-05: no round starts a loop). A revision that
a recorded measurement is against is a tag `baseline/<date>` (2026-11-11; the list: `.claude/rules/benchmarks.md`), so
that `bin/ab.py` can still run against it after the history was rewritten. The first one is `baseline/2026-11-11`; the
measurements before it name their state in words and by date

**Rejected**

- hybrid port
- extending the hand-rolled printer with median/IQR/JSON
- a per-step metric t_n / n (charged the source and the run to the steps: +54% for 1 step)
- citing a baseline by its commit hash (the history was squashed on 2026-11-10: the three commits the docs cited hung on
  the reflog only, which `git gc` prunes and no clone has)
- tags on those three commits (set and removed on 2026-11-11, the user's decision: they kept the squashed history, and
  `bin/ab.py` runs today's benchmarks on both sides, which import names those states lack)
- the date of a measurement in place of its revision, where the revision can be kept (a plan's step "reproduce" needs
  the code)
