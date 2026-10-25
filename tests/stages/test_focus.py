"""Tests of `strom._stages.focus`: wrapping a focus when lifting."""

from strom._stages.focus import Focus, counted, first_of, second_of


def test_lifting_wraps_a_focus() -> None:
    log: list[str] = []
    inner = Focus[str, str, str, str, str](
        split=lambda s: (s.upper(), "i"), merge=lambda b, k: b + k, finish=lambda k: log.append("inner " + k)
    )
    first: Focus[tuple[str, int], tuple[str, int], str, str, tuple[str, int]] = first_of(inner)
    a, first_kept = first.split(("x", 7))
    assert (a, first.merge(a + "!", first_kept)) == ("X", ("X!i", 7))
    second: Focus[tuple[int, str], tuple[int, str], str, str, tuple[str, int]] = second_of(inner)
    a, second_kept = second.split((7, "x"))
    assert (a, second.merge(a + "!", second_kept)) == ("X", (7, "X!i"))
    counted_focus = counted(inner, lambda sequence, delta: log.append(f"count {sequence} {delta:+}"))
    a, counted_kept = counted_focus.split(("x", 3))
    assert (a, counted_focus.merge(a + "!", counted_kept)) == ("X", ("X!i", 3))
    assert first.finish is not None and second.finish is not None and counted_focus.finish is not None
    first.finish(first_kept)
    second.finish(second_kept)
    counted_focus.finish(counted_kept)
    assert log == ["count 3 +1", "inner i", "inner i", "inner i", "count 3 -1"]  # the inner focus finishes first
    no_finish = Focus[str, str, str, str, None](split=lambda s: (s, None), merge=lambda b, _: b, finish=None)
    lifted: Focus[tuple[str, int], tuple[str, int], str, str, tuple[None, int]] = first_of(no_finish)
    assert lifted.finish is None
