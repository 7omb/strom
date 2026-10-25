"""Static typing tests of the public interface (mypy), and that the library contains no `Any`."""

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pytest
from helpers import ROOT

# Every check is a snippet of one generated module that mypy checks (after STATIC_SETUP), together with
# what it must result in: `reveals` the type mypy infers, `rejects` with an error containing the text,
# or `accepts` without an error. The markers identify a check in mypy's output and in the test ids.
STATIC_SETUP: str = """
from collections.abc import AsyncIterator, Iterator, Sequence
from strom import (Stage, Pools, PoolConfig, Threads, Processes, FromExecutor, async_stage, cpu_stage,
                      duplicate, where, first, flatten, identity, io_stage, product, stage, stream, Left, Right,
                      route, left, right, tag_by, gather, loop)
from strom.metrics import (Enclosing, Event, Hint, InputHandled, Recorder, RunStats, StatsRecorder, StepId,
                              StepStats)
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
@dataclass(frozen=True)
class Record:
    id: int
    payload: str
@dataclass(frozen=True)
class Score:
    record_id: int
    value: int
def parse(r: Record) -> Iterator[tuple[int, list[str]]]: yield r.id, r.payload.split()
def score(parsed: tuple[int, list[str]]) -> Iterator[Score]: yield Score(parsed[0], len(parsed[1]))
def render(s: Score) -> Iterator[str]: yield f"{s.record_id}:{s.value}"
def split_words(r: Record) -> list[str]: return r.payload.split()
def word_list(r: Record) -> Iterator[list[str]]: yield r.payload.split()
def has_even_id(r: Record) -> bool: return r.id % 2 == 0
ANALYZE: Stage[Record, Score] = cpu_stage(parse) | cpu_stage(score)
def _pools() -> Pools: raise NotImplementedError
pools = _pools()
def records_of(_: None) -> list[Record]: return [Record(id=1, payload="a b")]
RECORDS = [Record(id=1, payload="a b")]
recs: Stage[Record, Record] = identity()
async def async_records() -> AsyncIterator[Record]:
    yield Record(id=1, payload="a b")
splitter = io_stage(split_words)
def one_string() -> list[str]: return ["a b"]
strings: Stage[str, str] = identity()
def text_of(x: object) -> list[str]: return [str(x)]
recorder = StatsRecorder()
step_id = StepId((), 1, "s", 1)
async def chars(s: str) -> AsyncIterator[str]:
    yield s
def to_int(s: str) -> list[int]: return [int(s)]
def chars_list(s: str) -> list[str]: return list(s)
def halve(n: int) -> list[int]: return [n // 2]
def as_left(s: str) -> list[Left[str]]: return [Left(s)]
def countdown(n: int) -> list[Left[int] | Right[str]]: return [Left(n - 1)] if n > 0 else [Right(str(n))]
def mistyped_countdown(n: int) -> list[Left[str] | Right[str]]: return [Left(str(n))]
from contextlib import contextmanager
from strom import WorkerHandle, using, worker_handle
class Engine: ...
class SubEngine(Engine): ...
@contextmanager
def engine_of() -> Iterator[Engine]:
    yield Engine()
def rows(engine: Engine, query: str) -> Iterator[Record]: yield Record(id=1, payload=query)
def sub_rows(engine: SubEngine, query: str) -> list[Record]: return []
def _engine() -> WorkerHandle[Engine]: raise NotImplementedError
engine = _engine()
"""


@dataclass(frozen=True)
class StaticCheck:
    marker: str
    code: str  # one or more lines of the checked module
    kind: Literal["reveals", "rejects", "accepts"]
    expected: str  # the revealed type, or the text of the error message
    why: str


def reveals(marker: str, expression: str, type_: str, why: str = "") -> StaticCheck:
    return StaticCheck(marker, f"reveal_type({expression})", "reveals", type_, why)


def rejects(marker: str, code: str, message: str, why: str = "") -> StaticCheck:
    return StaticCheck(marker, code, "rejects", message, why)


def accepts(marker: str, code: str, why: str = "") -> StaticCheck:
    return StaticCheck(marker, code, "accepts", "", why)


STATIC_CHECKS = [
    reveals("R1", "recs | io_stage(split_words)", "Stage[static_check.Record, str]"),
    reveals(
        "R2",
        "recs | duplicate() | product(io_stage(split_words), ANALYZE)",
        "Stage[static_check.Record, tuple[str, static_check.Score]]",
    ),
    reveals(
        "R3",
        "recs | where(has_even_id) | duplicate() | first(io_stage(split_words))",
        "Stage[static_check.Record, tuple[str, static_check.Record]]",
    ),
    reveals("R4", "cpu_stage(split_words)", "Stage[static_check.Record, str]"),
    reveals("R6", "ANALYZE | io_stage(render)", "Stage[static_check.Record, str]"),
    reveals(
        "R8",
        "first(io_stage(split_words))",
        "strom._stages.model.Stage[tuple[static_check.Record, Never], tuple[str, Never]]",
        "first",
    ),
    reveals("R9", "recs | stage(split_words)", "Stage[static_check.Record, str]", "stage on the event loop"),
    reveals("R10", "recs | identity() | io_stage(split_words)", "Stage[static_check.Record, str]", "identity"),
    reveals("R11", "recs | io_stage(word_list) | flatten()", "Stage[static_check.Record, str]", "flatten over lists"),
    reveals(
        "R12",
        "io_stage(records_of) | io_stage(split_words) | cpu_stage(list)",
        "Stage[None, str]",
        "io and cpu stages, the items made from one input on the io pool",
    ),
    reveals("R13", "strings | async_stage(chars) | async_stage(chars)", "Stage[str, str]", "async"),
    reveals(
        "R16",
        "strings | tag_by(str.isdigit)",
        "Stage[str, strom._stages.model.Left[str] | strom._stages.model.Right[str]]",
        "tag_by",
    ),
    reveals(
        "R17",
        "strings | tag_by(str.isdigit) | route(stage(to_int), io_stage(chars_list))",
        "Stage[str, strom._stages.model.Left[int] | strom._stages.model.Right[str]]",
        "route",
    ),
    reveals(
        "R18",
        "left(stage(to_int))",
        "Stage[strom._stages.model.Left[str] | strom._stages.model.Right[Never], "
        "strom._stages.model.Left[int] | strom._stages.model.Right[Never]]",
        "left",
    ),
    reveals("R19", "strings | gather(io_stage(chars_list))", "Stage[str, list[str]]", "gather"),
    reveals("R20", "loop(stage(countdown))", "Stage[int, str]", "loop"),
    reveals(
        "R21", "first(gather(stage(halve)))", "Stage[tuple[int, Never], tuple[list[int], Never]]", "first of gather"
    ),
    StaticCheck(
        "R22",
        "async def r22() -> None:\n"
        "    async with stream(ANALYZE, RECORDS, pools) as outputs:\n"
        "        reveal_type(outputs)",
        "reveals",
        "typing.AsyncIterator[static_check.Score]",
        "a run's outputs, inside its block",
    ),
    rejects(
        "E1",
        "e1 = stream(ANALYZE, ['a'], pools)",
        'Cannot infer value of type parameter "I"',
        "inputs of another type",
    ),
    rejects("E2", "stream(ANALYZE, pools)", 'Missing positional argument "pools"', "no inputs"),
    rejects("E3", "x = recs | io_stage(render)", 'expected "Callable[[Record], Iterable[str]]"', "Record vs Score"),
    rejects(
        "E4",
        "y = recs | duplicate() | product(ANALYZE, ANALYZE) | stage(render)",
        'expected "Callable[[tuple[Score, Score]], Iterable[str]]"',
        "tuple vs Score",
    ),
    rejects("E6", "io_stage(5)", 'incompatible type "int"', "not callable"),
    rejects("E7", 'Threads(workers="4")', 'expected "int"', "wrong type"),
    rejects(
        "E8",
        "Pools.using(cpu=Threads(workers=1), io=Processes(workers=1))",
        'expected "Callable[[], StreamingBackend]"',
        "io_stage streams iterators: not on processes",
    ),
    rejects("E9", "stage(len)", 'type "Callable[[Sized], int]"', "returns one item, not an iterable"),
    rejects(
        "E14",
        'event = InputHandled(step_id, 0, 0.0, 1.0, 2.0, 1, 0.0, "done")\nevent.ended_at = 0.0',
        "final",
        "events are read-only",
    ),
    rejects("E15", 'Pools.open(cpu_workers=1, io_workers=1, cpu_backend="gpu")', "Literal['gpu']", "wrong literal"),
    rejects("E16", "stage([1])", 'incompatible type "list[int]"', "an iterable instead of a function"),
    rejects("E17", "stage(chars)", "AsyncIterator[str]", "async iterable on the event loop"),
    rejects("E18", "async_stage(one_string)", "list[str]", "plain iterable on async_stage"),
    rejects("E19", 'Enclosing(1, "p", "middle")', "Literal['middle']", "a join has two branches"),
    rejects(
        "E20",
        "stream(ANALYZE, RECORDS[0], pools)",
        'expected "Iterable[Record] | AsyncIterable[Record]"',
        "an item instead of inputs",
    ),
    rejects("E21", "stream(ANALYZE, 5, pools)", 'incompatible type "int"', "not iterable"),
    rejects("E23", "class MyStepStats(StepStats): pass", 'Cannot inherit from final class "StepStats"', "final"),
    rejects("E24", "class MyRunStats(RunStats): pass", 'Cannot inherit from final class "RunStats"', "final"),
    rejects("E25", "class MyHint(Hint): pass", 'Cannot inherit from final class "Hint"', "final"),
    rejects(
        "E26",
        "pools.config = PoolConfig(cpu=Threads(workers=1), io=Threads(workers=1))",
        'Cannot assign to final attribute "config"',
        "the backends were created from the configuration",
    ),
    rejects(
        "E27",
        "e27 = strings | tag_by(str.isdigit) | route(stage(halve), stage(to_int))",
        'expected "Callable[[str], Iterable[int]]"',
        "a branch of the wrong input type",
    ),
    rejects("E28", "Left(1).value = 2", "read-only", "tags are immutable"),
    rejects("E29", "class MyLeft(Left[int]): pass", 'Cannot inherit from final class "Left"', "final"),
    rejects(
        "E30",
        "e30 = loop(stage(mistyped_countdown))",
        'Cannot infer value of type parameter "A" of "loop"',
        "a Left that cannot be fed back",
    ),
    accepts("U2", "u2: Stage[Record, object] = splitter", "output widened (covariance)"),
    accepts("U3", "u3: Stage[Record, Sequence[str]] = io_stage(word_list)", "list[str] as Sequence[str]"),
    accepts(
        "U5",
        "events: list[Event] = []\nu5: list[Recorder] = [recorder, events.append]",
        "StatsRecorder and list.append are recorders",
    ),
    accepts(
        "U6",
        "async def u6() -> None:\n"
        "    async with Pools.open(cpu_workers=1, io_workers=1) as opened:\n"
        "        p: Pools = opened",
        "Pools.open",
    ),
    accepts(
        "U16",
        "async def u16() -> None:\n"
        "    async with Pools.using(cpu=FromExecutor(factory=ThreadPoolExecutor), io=Threads(workers=2)) as opened:\n"
        "        p: Pools = opened",
        "Pools.using with an executor class as the factory",
    ),
    accepts(
        "U7",
        "u7: Stage[tuple[Record, Record], tuple[str, Score]] = product(io_stage(split_words), ANALYZE)",
        "product of a 1:0..n branch",
    ),
    accepts(
        "U8",
        "u8: Stage[tuple[Record, Record], tuple[Record, Score]] = product(where(has_even_id), ANALYZE)",
        "product of a 1:0..1 branch",
    ),
    accepts(
        "U9",
        "u9: Stage[Left[str] | Right[int], Left[object] | Right[int]] = route(stage(to_int), stage(halve))",
        "route output widened (covariant tags)",
    ),
    accepts(
        "U10",
        "u10: Stage[str, Left[int] | Right[str]] = strings | stage(as_left) | route(stage(to_int), stage(chars_list))",
        "a stage emitting only Left values feeds a route",
    ),
    accepts("U11", 'u11 = Enclosing(1, "g", "body")', "the body of a gather or loop"),
    accepts("U12", "u12 = stream(stage(text_of), [1, 'a'], pools)", "inputs for a stage on object"),
    accepts("U13", "u13 = stream(splitter, (r for r in RECORDS), pools)", "a generator as inputs"),
    accepts(
        "U14",
        "async def u14() -> list[Score]:\n"
        "    async with stream(ANALYZE, RECORDS, pools) as outputs:\n"
        "        return [out async for out in outputs]",
        "the outputs, as an async iterator",
    ),
    accepts("U15", "u15 = stream(ANALYZE, async_records(), pools)", "async inputs"),
    # worker handles
    reveals("H1", "using(engine, rows)", "Using[str, static_check.Record]", "R, I and O inferred"),
    reveals("H2", "io_stage(using(engine, rows))", "Stage[str, static_check.Record]", "an ordinary function"),
    reveals("H3", "cpu_stage(using(engine, rows)) | io_stage(split_words)", "Stage[str, str]", "composes"),
    rejects("H4", "using(engine, sub_rows)", 'Argument 2 to "using" has incompatible type', "fn for another handle"),
    rejects("H5", "worker_handle(engine_of(), pools)", 'Argument 1 to "worker_handle"', "an opener, not its value"),
    accepts("H6", "h6: WorkerHandle[object] = engine", "a handle's type is covariant"),
    accepts("H7", "h7: Stage[str, object] = io_stage(using(engine, rows))", "output covariant"),
    accepts(
        "H8",
        "async def h8() -> list[Record]:\n"
        "    async with Pools.open() as opened, worker_handle(engine_of, opened) as db:\n"
        "        typed: WorkerHandle[Engine] = db\n"
        "        async with stream(io_stage(using(typed, rows)), ['q'], opened) as outputs:\n"
        "            return [out async for out in outputs]",
        "the handle of the async with block",
    ),
]


def run_mypy(config: str, check: Path | str) -> subprocess.CompletedProcess[str]:
    """Runs mypy with exactly this configuration (that of the surroundings is ignored) on a file or on
    source text. `strom` can be imported by it. The cache persists across
    runs, one per configuration, interpreter and xdist worker: configurations would invalidate each
    other's entries, and concurrent runs would contend for mypy's SQLite cache."""
    owner = "\0".join([config, sys.executable, os.environ.get("PYTEST_XDIST_WORKER", "")])
    cache = ROOT / ".mypy_cache" / f"static-tests-{hashlib.sha256(owner.encode()).hexdigest()[:16]}"
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp)
        (directory / "mypy.ini").write_text(config, encoding="utf-8")
        if isinstance(check, str):
            path = directory / "static_check.py"
            path.write_text(check, encoding="utf-8")
        else:
            path = check
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--config-file",
                str(directory / "mypy.ini"),
                "--no-error-summary",
                "--cache-dir",
                str(cache),
                str(path),
            ],
            capture_output=True,
            text=True,
            env={**os.environ, "MYPYPATH": str(ROOT / "src")},
        )


@pytest.fixture(scope="module")
def mypy_output() -> dict[str, str]:
    """mypy's messages for the static checks, by marker ("" for the setup)."""
    pytest.importorskip("mypy")
    lines: list[str] = STATIC_SETUP.strip().splitlines()
    marker_of_line = dict.fromkeys(range(1, len(lines) + 1), "")
    for check in STATIC_CHECKS:
        for line in check.code.splitlines():
            lines.append(line)
            marker_of_line[len(lines)] = check.marker
    result = run_mypy("[mypy]\nstrict = True\n", "\n".join(lines) + "\n")
    assert result.returncode in (0, 1), f"mypy failed to run:\n{result.stdout}{result.stderr}"
    by_marker: dict[str, str] = {}
    for line in result.stdout.splitlines():
        # the number after the file name: a path may contain colons itself (Windows drive letters)
        number = re.search(r"static_check\.py:(\d+):", line)
        assert number is not None, f"unexpected line in mypy's output: {line}"
        marker = marker_of_line[int(number[1])]
        by_marker[marker] = by_marker.get(marker, "") + line + "\n"
    assert "" not in by_marker, "the setup of the static checks is not clean:\n" + by_marker[""]
    return by_marker


@pytest.mark.parametrize("check", STATIC_CHECKS, ids=[check.marker for check in STATIC_CHECKS])
def test_static_typing(mypy_output: dict[str, str], check: StaticCheck) -> None:
    output = mypy_output.get(check.marker, "")
    message = f"{check.why}:\n{output}"
    error = ": error:"  # mypy's error lines; messages and revealed types may contain the word itself
    if check.kind == "reveals":  # the expression must also be accepted: mypy reveals types of rejected calls too
        assert error not in output, message
        assert check.expected in output, message
    elif check.kind == "rejects":
        assert error in output, message
        assert check.expected in output, message
    else:
        assert error not in output, message


def test_library_contains_no_any() -> None:
    # No `Any` in annotations or expressions (mypy --disallow-any-expr). Note: mypy itself narrows
    # `case Step():` etc. to [Any, Any] type arguments without reporting it; pyright and ty don't.
    pytest.importorskip("mypy")
    # The source package, not `P.__file__`: installed (tox), mypy took site-packages for a source directory.
    result = run_mypy("[mypy]\nstrict = True\ndisallow_any_expr = True\n", ROOT / "src" / "strom")
    assert result.returncode == 0, result.stdout + result.stderr
