# Markdown formatter

mdformat with mdformat-gfm and mdformat-frontmatter (2026-11-10), as a pre-commit hook in pre-commit's own venv (pure
Python, runs on NixOS; no `uv.lock` change, which would make every example's lock stale); `.mdformat.toml`: `wrap = 120`
(paragraphs filled to ruff's line-length, so wrapping is uniform and automatic), consecutive numbering, compact tables.
It checks that the rendered HTML is unchanged and escapes `<` and `[` where they could start markup. Not wrapped: table
rows (GFM rows are one line), code blocks, front matter, long link targets. So tables hold only short cells, every line
stays within 120 characters (`bin/check_docs.py`, in `make lint`; front matter, lines with a URL and, until
restructured, the tables of `docs/research/` exempt), and this file has a section per topic instead of a table row

**Rejected**

- this file as a table (rows of up to 6,500 characters: unreadable unwrapped, and every edit a diff of the whole row)
- HTML tables (mdformat leaves them alone, but the source is hard to read and edit)
- `<br>` in table cells (still one line)
- Prettier (Node, not in the dev shell; mdformat's docs list AST-changing bugs)
- rumdl and dprint (native PyPI binaries need nix-ld, like ruff)
- padded tables (the long rows of `docs/decisions.md` and `ARCHITECTURE.md` became thousands of columns wide)
- `wrap = "keep"` (hand wrapping, nothing keeps lines under 120 or uniform)
