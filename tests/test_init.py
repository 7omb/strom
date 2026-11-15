"""Tests of the package as users see it: the public interface, the example of `README.md` and those of the user
guide."""

import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest
from helpers import ROOT, neg, readme_example

import strom as P
from strom import backends, metrics, testing


def test_api_requires_explicit_values() -> None:
    same: P.Stage[int, int] = P.identity()
    # each checker rejects these calls, and each has an ignore comment of its own (`.claude/rules/typing.md`)
    with pytest.raises(TypeError):
        P.PoolConfig()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        P.stream(same, [1])  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        P.flatten(concurrency=2)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match="abstract"):
        P.Stage(name="x")


def test_public_interface() -> None:
    assert sorted(P.__all__) == sorted(
        [
            "Stage",
            "CpuBackendKind",
            "PoolConfig",
            "Pools",
            "Threads",
            "Processes",
            "FromExecutor",
            "default_cpu_workers",
            "default_io_workers",
            "worker_handle",
            "WorkerHandle",
            "using",
            "stage",
            "async_stage",
            "io_stage",
            "cpu_stage",
            "where",
            "flatten",
            "identity",
            "swap",
            "fst",
            "snd",
            "untag",
            "duplicate",
            "first",
            "second",
            "product",
            "Left",
            "Right",
            "route",
            "left",
            "right",
            "tag_by",
            "gather",
            "loop",
            "stream",
            "RunFailed",
        ]
    )


def test_public_interface_of_the_metrics() -> None:
    expected = [
        "Recorder",
        "StatsRecorder",
        "combine_recorders",
        "RunStats",
        "StepStats",
        "diagnose",
        "Hint",
        "Event",
        "RunStarted",
        "InputHandled",
        "TaskFinished",
        "PoolTaskFinished",
        "RunFinished",
        "Outcome",
        "StepId",
        "Enclosing",
        "Part",
    ]
    assert sorted(metrics.__all__) == sorted(expected)
    assert {name for name in vars(metrics) if not name.startswith("_")} == set(expected)  # nothing else shows
    assert not set(expected) & set(vars(P))  # one import path per name: none also at the top level


def test_public_interface_for_backend_implementers() -> None:
    assert sorted(backends.__all__) == sorted(
        [
            "Backend",
            "StreamingBackend",
            "WorkerId",
            "init_worker",
            "release_scope",
            "init_handles",
            "close_process_handle",
            "close_all_process_handles",
        ]
    )


def test_the_readme_example_runs(tmp_path: Path) -> None:
    """As a script of its own: its `cpu_stage` runs in worker processes, which import its `__main__`."""
    done = subprocess.run(
        [sys.executable, readme_example(tmp_path)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    *values, total = done.stdout.splitlines()
    assert len(values) == 20, "one per input"
    assert total == f"total: {sum(map(int, values))}" == "total: 14960", "as the user guide says"


def test_the_quick_start_of_the_user_guide_shows_the_readme_example(tmp_path: Path) -> None:
    example = readme_example(tmp_path).read_text(encoding="utf-8")
    assert textwrap.indent(example, "    ") in (P.__doc__ or "")
    for text in (P.__doc__ or "", (ROOT / "README.md").read_text(encoding="utf-8")):
        assert "`total: 14960`" in text, "the output that both state"


def upto(n: int) -> Iterator[int]:
    yield from range(1, n + 1)


def letters(text: str) -> Iterator[str]:
    yield from text


def halves(n: int) -> Iterator[int]:
    yield n // 2


def is_even(n: int) -> bool:
    return n % 2 == 0


def shown(item: object) -> str:
    """An item as the user guide writes it: a tag without the name of its field."""
    match item:
        case P.Left(value):
            return f"Left({shown(value)})"
        case P.Right(value):
            return f"Right({shown(value)})"
        case _:
            return repr(item)


def guide_line[I, O](call: str, stage: P.Stage[I, O], inputs: list[I], outputs: list[O], remark: str = "") -> str:
    """The line of the user guide for a stage on these inputs, once the reference semantics gave these outputs."""
    assert testing.bag(testing.evaluate(stage, inputs)) == testing.bag(outputs), call
    return f"{call} {', '.join(map(repr, inputs))} => {' '.join(map(shown, outputs)) or 'nothing'}{remark}"


def test_the_examples_of_the_user_guide_give_the_outputs_it_shows() -> None:
    lifted: P.Stage[tuple[int, str], tuple[int, str]] = P.first(P.stage(upto))
    pairs = P.product(P.stage(upto), P.stage(letters))
    twice: P.Stage[int, tuple[int, int]] = P.duplicate()
    tags: list[P.Left[int] | P.Right[int]] = [P.Left(2), P.Right(-5)]
    dropped = ": a branch without outputs drops the input"
    lines = [
        guide_line("first(upto)", lifted, [(2, "x")], [(1, "x"), (2, "x")]),
        guide_line("product(upto, letters)", pairs, [(2, "ab")], [(1, "a"), (1, "b"), (2, "a"), (2, "b")]),
        guide_line("product(upto, letters)", pairs, [(2, "")], [], dropped),
        guide_line(
            "duplicate() | product(upto, neg)", twice | P.product(P.stage(upto), P.stage(neg)), [2], [(1, -2), (2, -2)]
        ),
        guide_line(
            "tag_by(is_even) | route(halves, neg)",
            P.tag_by(is_even) | P.route(P.stage(halves), P.stage(neg)),
            [4, 5],
            tags,
        ),
        guide_line("gather(upto)", P.gather(P.stage(upto)), [3, 0], [[1, 2, 3], []]),
    ]
    in_the_guide = [" ".join(line.split()) for line in (P.__doc__ or "").splitlines() if "=>" in line]
    assert in_the_guide == lines, "every example line of the guide, and no other"
