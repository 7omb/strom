---
paths:
  - "flake.nix"
  - "flake.lock"
  - ".envrc"
---

# The jail

- Claude Code runs in the jail of `flake.nix` (`jailed-claude`) with the packages of `claudePkgs` only: no `nix`, no git
  identity (a commit needs `GIT_AUTHOR_*` and `GIT_COMMITTER_*` in the environment), no `ps` (processes are under
  `/proc`), no `taskset` (`os.sched_setaffinity`; `bin/ab.py --cpus`).
