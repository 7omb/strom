---
paths:
  - "bin/ab.py"
  - "bin/mutant.py"
  - "bin/typing_snapshot.py"
  - "bin/collect_ids.py"
  - "bin/baseline.py"
  - "tools/strom_tools/change_checks/revisions.py"
---

# Baselines

`bin/baseline.py` prints a baseline of an uncommitted tree (the second change of a session, moved or new modules): a
commit of the working tree with its untracked files, made beside the index. Pass its hash as REV. The revision `:index`
is the index as it is.

- Never run a bare `git stash`, because `pop` without `--index` brings what the user staged back unstaged (repaired
  2026-11-10 with `git read-tree`). The deny rules cover push, pop, apply and drop, not the bare command.
- When `bin/ab.py` says that the baseline lacks a module the benchmarks import (2026-11-11: `strom.metrics`), make a
  baseline that has it. Set `GIT_INDEX_FILE` to a scratch file first, so that the `git add` goes into that file and not
  into the user's index, and set `GIT_AUTHOR_*` and `GIT_COMMITTER_*`, because the jail has no git identity. Then:
  1. `git read-tree BASE`
  2. `git add` the module
  3. `git commit-tree $(git write-tree) -p BASE -m baseline`
