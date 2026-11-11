---
paths:
  - "bin/rename.py"
  - "tools/strom_tools/renames.py"
---

# Renames

- A module moves with `bin/rename.py OLD NEW` (two paths): it rewrites the imports and sorts them. Moved by hand, the
  edit hook sorts imports at once, and an import of the old path counts as third-party and jumps above `import strom`
  (2026-11-11).
- The move stays unstaged (the script prints the `git add`): until the user stages it, a doc that cites the new path
  fails the docs check as untracked, and `--against :index` compares with the module at its old path.
