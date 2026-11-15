from tool_helpers import write

from strom_tools.docs_check.prose_counts import LIMITS, Count, CountKind, counts, rendered
from strom_tools.workspace.repository import Repository


def found(repository: Repository, text: str) -> list[Count]:
    return counts(repository, write(repository, "docs/doc.md", text))


def test_more_than_two_semicolons_in_a_sentence_are_counted(repository: Repository) -> None:
    assert found(repository, "One; two; three; four.\n") == [Count("docs/doc.md", 1, CountKind.SEMICOLONS, 3)]
    assert found(repository, "One; two; three. mypy says four; five.\n") == [], "per sentence"
    assert found(repository, "One `a; b; c; d` span.\n") == [], "not in a code span"


def test_a_long_parenthesis_is_counted_but_under_rejected(repository: Repository) -> None:
    inner = " ".join(["word"] * (LIMITS[CountKind.PARENTHESIS_WORDS] + 1))
    assert found(repository, f"Text.\n\nA reason ({inner}) here (and a short one).\n") == [
        Count("docs/doc.md", 3, CountKind.PARENTHESIS_WORDS, 13)
    ]
    rejected = f"**Rejected**\n\n- an alternative ({inner})\n"
    assert found(repository, rejected) == [], "there the parenthesis is the reason"


def test_a_count_is_rendered_with_what_to_look_for() -> None:
    assert rendered(Count("d.md", 3, CountKind.SEMICOLONS, 4)) == "d.md:3: 4 semicolons in a sentence: a list?"
