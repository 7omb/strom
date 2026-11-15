# Git index

The index is the user's, and Claude neither stages nor unstages, because the user keeps a state staged and compares
Claude's changes with it. The comparison is `git diff`, or the revision `:index` of the scripts in `bin/`. The rule is
in `CLAUDE.md` (Process). A `deny` rule in `.claude/settings.json` enforces it for Claude's commands, and the tools keep
to it: `strom_tools.workspace.git_files` runs no git command that changes the index (tested).

**Rejected**

- Claude staging new files so that the docs check passes (until 2026-11-11, by the rules of that time: a session staged
  all its work with `git add -A`, and the user could no longer tell it from what had been staged before)
- Claude staging a version as a baseline for `--against :index` (the user could no longer tell it from the staged state
  either; and the jail's missing git identity, the reason at the time, does not stop `git commit-tree` with the identity
  in the environment)
- `git mv` for a tracked file that `bin/rename.py` moves (until 2026-11-11: it staged the move, and `:index` then held
  the new path with the old contents; git finds a move by content once both paths are staged)
- the Stop hook blocking for an untracked citation, or telling the user at every stop (a block once per turn, or a
  message at every stop, for what only the user can change)
- the docs check accepting untracked files outside the commit hook (a second definition of lint, see
  `docs/decisions/docs-check.md`)
