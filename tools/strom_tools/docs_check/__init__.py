"""The check of the docs (`bin/check_docs.py`). Import order: `doc_lines` (a doc's lines and the part each is in);
`rule_notes` (Claude Code's rules files, without git: the hooks read them after every Bash call) and `passages` (a
doc's paragraphs and list items, and their sentences); `decision_form` (what a decision's text must have) and
`prose_counts` (what prompts a look, for a review); then `doc_problems` (what a doc cites that is not tracked, its
long lines, the problems of a rules file and of a decision)."""
