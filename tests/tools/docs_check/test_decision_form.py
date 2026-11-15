from strom_tools.docs_check.decision_form import (
    FIRST_SENTENCE_WORDS,
    FormProblem,
    LongFirstSentence,
    ManyNumbers,
    NoFirstSentence,
    NumberSeries,
    PlainArrow,
    UnreasonedRejection,
    form_problems,
)
from strom_tools.docs_check.doc_lines import lines_of

START = "# Topic\n\nThe shards are kept, because merging them costs a copy.\n"
"""Three lines of a decision that has its form."""


def found(text: str) -> list[FormProblem]:
    return form_problems("d.md", list(lines_of(text)))


def test_a_decision_that_starts_with_a_short_sentence_has_its_form() -> None:
    assert found(START) == []
    assert found(START + "More follows; fragments (and asides) too\n\n**Rejected**\n\n- merging (a copy)\n") == []


def test_a_decision_starts_with_a_paragraph_that_ends_a_sentence() -> None:
    assert found("# Topic\n\nShards; no merging (a copy)\n\nA sentence comes later.\n") == [NoFirstSentence("d.md", 3)]
    in_a_span_or_an_abbreviation = "# Topic\n\nShards as in `a.b. c`, e.g. kept\n"
    assert found(in_a_span_or_an_abbreviation) == [NoFirstSentence("d.md", 3)]
    for no_lead in ("# Topic\n", "# Topic\n\n**Rejected**\n\n- merging (a copy)\n", "# Topic\n\n| a | table |\n"):
        assert found(no_lead) == [NoFirstSentence("d.md", 1)], no_lead


def test_the_first_sentence_has_a_limit_of_words_and_a_code_span_is_one() -> None:
    words = " ".join(["word"] * (FIRST_SENTENCE_WORDS - 1))
    assert found(f"# Topic\n\n{words}\n`a span of five words`. A second sentence may be long.\n") == []
    over = f"# Topic\n\n{words} two more.\n\nShort.\n"
    assert found(over) == [LongFirstSentence("d.md", 3, FIRST_SENTENCE_WORDS + 1)]


def test_a_rejected_alternative_ends_with_its_reason_in_parentheses() -> None:
    reasoned = "- merging (a copy per shard)\n- batches (until 2026): they wait\n  - a nested item is no alternative\n"
    assert found(f"{START}\n**Rejected**\n\n{reasoned}\n**Measured**\n\n- nor is an item of another list\n") == []
    unreasoned = (
        "- `merge(all)`\n- sorting them\n  on every read\n- a 1:1 mapping at 10:30\n- merging (a copy) of shards\n"
    )
    assert found(f"{START}\n**Rejected**\n\n{unreasoned}") == [
        UnreasonedRejection("d.md", line) for line in (7, 8, 10, 11)
    ]
    assert found(f"{START}\n- an item that is no rejected alternative\n") == []


def test_numbers_separated_by_slashes_are_a_series() -> None:
    series = found(f"{START}\nRatios of 0.56 / 0.41 / 0.34 for 1/3/6 steps.\n")
    assert series == [NumberSeries("d.md", 5, "0.56 / 0.41 / 0.34")]
    for fine in ("on 3.14/3.14t", "an A/B run", "`1/2` of it", "+1/-1 cancel", "from 2026-11-06/2026-11-11"):
        assert found(f"{START}\nMeasured {fine} here.\n") == [], fine
    for taken_for_one in ("about 1/3 of the runs", "on Python 3.13/3.14", "a 50/50 split"):
        (problem,) = found(f"{START}\nMeasured {taken_for_one} here.\n")
        assert isinstance(problem, NumberSeries), "known: its message says to write it in words or in a code span"


def test_a_sentence_holds_at_most_six_numbers() -> None:
    seven = "Runs of 1, 2, 3, 4, 5, 6 and 7 items."
    assert found(f"{START}\n{seven}\n") == [ManyNumbers("d.md", 5, 7)]
    assert found(f"{START}\n**Rejected**\n\n- batches ({seven})\n") == [ManyNumbers("d.md", 7, 7)]
    assert found(f"{START}\nRuns, e.g. of 1, 2, 3, 4, 5, 6 and 7 items.\n") == [ManyNumbers("d.md", 5, 7)]
    assert found(f"{START}\nRuns of 1, 2, 3 and 4 items. mypy found 5, 6 and 7 more.\n") == [], "two sentences"
    no_measurements = "On 2026-11-11 with `-n 15`, F401, 3.14t, 0837df3e and 60ms: 1, 2, 3, 4, 5 and 6."
    assert found(f"{START}\n{no_measurements}\n") == [], "a date, a span, a code, a version, a hash, a unit attached"
    assert found(f"{START}\n| {seven} |\n\n```\n{seven}\n```\n") == [], "a table row and a code block"


def test_an_arrow_between_numbers_is_the_unicode_one() -> None:
    assert found(f"{START}\nThe suite took 10.7 -> 4.8 s.\n") == [PlainArrow("d.md", 5)]
    assert found(f"{START}\nIt maps (a, 1) -> (b, 1) and `1 -> 2`, and 10.7 → 4.8 s is the form.\n") == []
    assert found(f"{START}\nThe function maps 1 -> 2.\n") == [PlainArrow("d.md", 5)], "known: a mapping, for a span"


def test_the_problems_come_in_the_order_of_the_lines_after_that_of_the_first_sentence() -> None:
    text = "# Topic\n\nShards 1/2\n\n- 3 -> 4\n\n**Rejected**\n\n- merging\n"
    assert found(text) == [
        NoFirstSentence("d.md", 3),
        NumberSeries("d.md", 3, "1/2"),
        PlainArrow("d.md", 5),
        UnreasonedRejection("d.md", 9),
    ]
