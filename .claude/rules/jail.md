---
paths:
  - "flake.nix"
  - "flake.lock"
  - ".envrc"
---

# The jail

- Claude Code runs in the jail of `flake.nix` (`jailed-claude`) with the packages of `claudePkgs` only: no `nix`, no git
  identity (a commit needs `GIT_AUTHOR_*` and `GIT_COMMITTER_*` in the environment), no `/sys`.
- Processes: `ps`, `pgrep` and `pkill` (leftover pytest and forkserver workers: `pgrep -af forkserver`); pinning a
  probe: `taskset -c 0-11 CMD`.
- ptrace reaches only a process's own children (Yama scope 1): `py-spy record -o prof.txt -f raw -- CMD` profiles a
  command it starts (`--subprocesses` for pool workers), `py-spy dump --pid` and `python -m asyncio pstree` fail on
  another process (2026-11-11). A hung test: `kill -USR1 PID` writes its stacks to `.checks/stacks/PID.txt`.
- `hyperfine 'CMD'` times a short command over many runs (the hook command: pipe a recorded event into
  `python3 .claude/hooks/dispatch.py`).
