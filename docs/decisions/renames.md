# Renames

`bin/rename.py` renames an identifier in the code, and it moves a file with its imports and with what the docs say of it
(the move: 2026-11-11, from a retrospective of 8 sessions). How it treats the index: `docs/decisions/git-index.md`; how
it runs the fixers: `docs/decisions/checks.md`.

**Rejected**

- moving the test module along with a module (it would have to know the test layout; a second call does it)
