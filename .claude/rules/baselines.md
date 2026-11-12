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

A baseline of an uncommitted tree (the second change of a session, moved or new modules): `bin/baseline.py` prints a
commit of the working tree with its untracked files, made beside the index, which is the user's (`CLAUDE.md`, Process);
pass the hash as REV. The index as it is: `:index`.

- Never a bare `git stash` (deny rules cover push, pop, apply and drop, not the bare command): `pop` without `--index`
  brings what the user staged back unstaged (repaired 2026-11-10 with `git read-tree`).
- A baseline for `bin/ab.py` that lacks a module the benchmarks import (it says so): with `GIT_INDEX_FILE` set to a
  scratch file (only then: the `git add` goes into that file, not into the user's index), `git read-tree BASE`,
  `git add` that module, `git commit-tree $(git write-tree) -p BASE -m baseline`, with `GIT_AUTHOR_*` and
  `GIT_COMMITTER_*` set (the jail has no git identity; 2026-11-11: `strom.metrics`).
