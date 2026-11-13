"""The check of the docs (`bin/check_docs.py`). Import order: `doc_lines` (a doc's lines and the part each is in);
`rule_notes` (Claude Code's rules files, without git: the hooks read them after every Bash call); then
`doc_problems` (what a doc cites that is not tracked, its long lines, the problems of a rules file)."""
