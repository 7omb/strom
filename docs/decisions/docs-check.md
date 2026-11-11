# Docs check

`bin/check_docs.py` (in `make lint`) accepts a cited path or library name only if it is tracked (2026-11-11): a clone
has only what is tracked, so a doc that cites a new file fails until the user adds the file (`git add`: the check says
so; Claude leaves the index alone, see `git-index.md`)

**Rejected**

- accepting what merely exists in the working tree (until 2026-11-11: `docs/research/` was untracked and cited, and a
  fresh clone failed `make lint` with four missing references)
- `git add -N` for a new file (with an intent-to-add entry `git stash create`, the baseline of `bin/ab.py`, fails, and
  the revision `:index` gets an empty file)
- the stricter check only in the commit hook (a second definition of lint, see `checks.md`)
