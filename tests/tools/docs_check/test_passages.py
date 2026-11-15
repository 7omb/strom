from strom_tools.docs_check.doc_lines import Context, lines_of
from strom_tools.docs_check.passages import SPAN, Passage, passages_of, sentences_of


def test_the_passages_are_the_paragraphs_and_the_list_items() -> None:
    text = (
        "---\ntitle: x\n---\n# A\n\nOne\ntwo.\n\n- first\n  more\n  - nested\n1. third\n\n| a |\n\n"
        "```\ncode\n```\n**Rejected**\n\n- old\n"
    )
    assert list(passages_of(lines_of(text))) == [
        Passage(6, "One two.", Context.PROSE, is_item=False, indent=0),
        Passage(9, "first more", Context.PROSE, is_item=True, indent=0),
        Passage(11, "nested", Context.PROSE, is_item=True, indent=2),
        Passage(12, "third", Context.PROSE, is_item=True, indent=0),
        Passage(19, "**Rejected**", Context.REJECTED, is_item=False, indent=0),
        Passage(21, "old", Context.REJECTED, is_item=True, indent=0),
    ]


def test_a_code_span_is_one_word_without_what_it_holds() -> None:
    (passage,) = passages_of(lines_of("Run `a.b 1/2` twice,\nor `c`.\n"))
    assert passage.text == f"Run {SPAN} twice, or {SPAN}."


def test_a_sentence_ends_with_a_full_stop_that_ends_no_abbreviation() -> None:
    ended, rest = sentences_of("One. mypy says two! Three, e.g. four? Five (six.) seven")
    assert ended == ["One.", "mypy says two!", "Three, e.g. four?", "Five (six."]
    assert rest == ") seven"
    assert sentences_of("No end, cf. 3.14 and a.b") == ([], "No end, cf. 3.14 and a.b")
    assert sentences_of("") == ([], "")
