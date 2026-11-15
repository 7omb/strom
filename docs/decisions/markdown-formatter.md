# Markdown formatter

The docs are formatted by mdformat with mdformat-gfm and mdformat-frontmatter, a pre-commit hook in pre-commit's own
venv, because it is pure Python and so runs on NixOS. It needs no change of `uv.lock`, which would make every example's
lock stale.

- `.mdformat.toml` sets `wrap = 120` (paragraphs filled to ruff's line-length, so wrapping is uniform and automatic),
  consecutive numbering and compact tables.
- mdformat checks that the rendered HTML is unchanged and escapes `<` and `[` where they could start markup.
- It does not wrap table rows (GFM rows are one line), code blocks, front matter and long link targets. So tables hold
  only short cells, and every line stays within 120 characters (`bin/check_docs.py`, in `make lint`); front matter,
  lines with a URL and, until restructured, the tables of `docs/research/` are exempt.
- The decisions are a file per topic instead of a table row each.
- The Stop hook formats the changed docs and runs the docs check (`strom_tools.hooks.docs_fixes`, 2026-11-11): one
  session had run the formatter by hand twelve times.

**Rejected**

- the decisions as a table (rows of up to 6,500 characters: unreadable unwrapped, and every edit a diff of the whole
  row)
- HTML tables (mdformat leaves them alone, but the source is hard to read and edit)
- `<br>` in table cells (still one line)
- Prettier (Node, not in the dev shell; mdformat's docs list AST-changing bugs)
- rumdl and dprint (native PyPI binaries need nix-ld, like ruff)
- padded tables (the long rows of `docs/decisions.md` and `ARCHITECTURE.md` became thousands of columns wide)
- `wrap = "keep"` (hand wrapping, nothing keeps lines under 120 or uniform)
- formatting a doc after each edit (mdformat through pre-commit takes 0.6 s per call, and the file would change under
  the edits that follow in the turn)
