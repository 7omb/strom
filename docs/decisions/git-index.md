# Index

The index is the user's (2026-11-11): Claude neither stages nor unstages. The user keeps a state staged and compares
Claude's changes with it (`git diff`, and the revision `:index` of the scripts in `bin/`); what needs staging is a
command at the end of a report (`CLAUDE.md`, Process). Consequences: a new file that a doc cites keeps `make lint`
failing until the user stages it; a file is deleted without `git rm`; a baseline that Claude needs is a commit made
beside the index (`.claude/rules/baselines.md`). The tools keep to it: `strom_tools.workspace.git_files` runs no git
command that changes the index (tested); `bin/rename.py` moves a file in the working tree only and prints the `git add`
for the two paths; the Stop hook does not block Claude for a citation that is only untracked, which Claude could not
fix, but tells the user, once per set of such citations (`strom_tools.hooks.docs_fixes`). A `deny` rule for the staging
commands in `.claude/settings.json` enforces it for Claude's own commands; the user writes that file

**Rejected**

- Claude staging new files so that the docs check passes (until 2026-11-11, by the rules of that time: a session staged
  all its work with `git add -A`, and the user could no longer tell it from what had been staged before)
- Claude staging a version as a baseline for `--against :index` (the same; and the jail's missing git identity, the
  reason at the time, does not stop `git commit-tree` with the identity in the environment)
- `git mv` for a tracked file that `bin/rename.py` moves (until 2026-11-11: it staged the move, and `:index` then held
  the new path with the old contents; git finds a move by content once both paths are staged)
- the Stop hook blocking for an untracked citation (once per turn, for what only the user can change), or telling the
  user at every stop
- the docs check accepting untracked files outside the commit hook (a second definition of lint, see `docs-check.md`)
