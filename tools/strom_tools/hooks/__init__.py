"""The Claude Code hooks of this project. Import order: `hook_events`; then the handlers, which import nothing of
each other (`command_guards`, `python_fixes`, `docs_fixes`, `rules_loading`, `friction_notes`, `context_notes`);
then `dispatcher`."""
