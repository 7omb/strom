---
paths:
  - "benchmarks/**"
---

# Benchmarks

One measurement per test (a second `benchmark()` call fails), grouped with `pytest.mark.benchmark(group=…)` so a
reference and the pipeline share a table; ratios between benchmarks with different item counts are not comparable. A 10%
`--benchmark-compare-fail` flagged an unchanged benchmark in the noisy sandbox: tune it on the target machine.

```
uv run pytest benchmarks/benchmark.py [--benchmark-autosave | --benchmark-compare --benchmark-compare-fail=min:10%]
BENCH_SCALE=0.2 uv run pytest benchmarks/benchmark.py --benchmark-min-rounds=1 --benchmark-max-time=0.1
uv run pytest benchmarks/benchmark.py --benchmark-disable   # each benchmark once, no timing: results only
```

A recorded measurement names its baseline by a tag, never by a commit hash: a rewritten history leaves a hash on the
reflog only (2026-11-10). Tag the revision before citing it: `git tag baseline/<date> REV` (lightweight: the jail has no
git identity); `bin/ab.py` takes the tag as a revision. Pushing it is the user's step (`git push origin TAG`). The
baselines (`git tag -l 'baseline/*'`):

| Tag | The state it keeps |
| -- | -- |
| `baseline/2026-11-11` | the built-in backends on a pool of their own, the metrics in `strom.metrics` |

The measurements before it name their state in words and by date: those states went with the squashed history.
