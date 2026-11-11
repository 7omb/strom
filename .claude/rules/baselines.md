---
paths:
  - "bin/ab.py"
  - "bin/mutant.py"
  - "bin/typing_snapshot.py"
  - "bin/collect_ids.py"
  - "tools/strom_tools/change_checks/revisions.py"
---

# Baselines

A baseline is a commit made beside the index, which is the user's (`CLAUDE.md`, Process); pass its hash as REV (the
scripts reject a bare tree id). The jail has no git identity: set `GIT_AUTHOR_*` and `GIT_COMMITTER_*`.

- Never a bare `git stash` (deny rules cover push, pop, apply and drop, not the bare command): `pop` without `--index`
  brings what the user staged back unstaged (repaired 2026-11-10 with `git read-tree`). The uncommitted tree:
  `git stash create` (a commit, nothing changes; untracked files left out).
- The index: `git commit-tree $(git write-tree) -p HEAD -m baseline`.
- The working tree with its untracked files (moved or new modules): with `GIT_INDEX_FILE` set to a scratch file (only
  then: the `git add` goes into that file, not into the user's index), `git read-tree HEAD`,
  `git add -A -- src tests benchmarks bin tools examples pyproject.toml`, then `git commit-tree` as above (2026-11-11).
- A baseline for `bin/ab.py` that lacks a module the benchmarks import (it says so): in the scratch index,
  `git read-tree BASE`, `git add` that module, `git commit-tree` (2026-11-11: `strom.metrics`).
