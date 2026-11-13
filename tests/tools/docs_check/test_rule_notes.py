from tool_helpers import write

from strom_tools.docs_check.rule_notes import RuleNote, rule_notes
from strom_tools.workspace.repository import Repository


def test_rule_notes_are_the_rules_files_with_their_paths_and_body(repository: Repository) -> None:
    write(
        repository,
        ".claude/rules/tests.md",
        '---\npaths:\n  - "tests/**"\n  - docs/*.md\n---\n\n# Tests\n\nNo sleeps.\n',
    )
    write(repository, ".claude/rules/notes.md", "# Notes\n\n---\n\nNo front matter.\n")
    directory = repository.root / ".claude/rules"
    assert rule_notes(repository) == [
        RuleNote(directory / "notes.md", [], "# Notes\n\n---\n\nNo front matter."),
        RuleNote(directory / "tests.md", ["tests/**", "docs/*.md"], "# Tests\n\nNo sleeps."),
    ]
