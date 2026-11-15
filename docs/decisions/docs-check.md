# Docs check

`bin/check_docs.py` (in `make lint`) accepts a cited path or library name only if it is tracked, because a clone has
only what is tracked (2026-11-11). The check is in `make lint` since 2026-11-06: stale references had been found by hand
in four sessions. What it asks of a decision: `docs/decisions/decision-form.md`.

**Rejected**

- accepting what merely exists in the working tree (until 2026-11-11: `docs/research/` was untracked and cited, and a
  fresh clone failed `make lint` with four missing references)
- `git add -N` for a new file (with an intent-to-add entry `git stash create`, the baseline of `bin/ab.py`, fails, and
  the revision `:index` gets an empty file)
- the stricter check only in the commit hook (a second definition of lint, see `docs/decisions/checks.md`)
- mutmut-style generated checks for docs (the references are explicit, a plain existence check suffices)
