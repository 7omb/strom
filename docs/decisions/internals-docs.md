# Internals docs

`ARCHITECTURE.md` at the root is the one starting point for contributors and agents, not a part of the package
docstring, because there the internals showed users the naming conventions and went stale with the module split. It
holds the overview, the repository, the packages, the design notes and the conventions; `help(strom)` is the user guide
only. The form of its design notes and name lists and of `GLOSSARY.md` is in `.claude/rules/docs.md`; the evidence for
it is in `docs/research/docs-writing.md` (4.8, 4.9, 5.2, 5.7).

**Rejected**

- `docs/internals.md` beside design notes and code conventions in `CLAUDE.md` (two places, the conventions hidden from
  human contributors)
- tables for the names (a table takes about a third more tokens than plain lines, and a list has a name per line too)
- the overview and the packages out of the required reading altogether (the evidence against overviews is from issue
  resolution in other repositories; the layers say where a module may import from)
- an alphabetical glossary (a term is found by search; the groups place a term among its neighbours)
