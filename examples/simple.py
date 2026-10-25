# /// script
# requires-python = ">=3.14"
# dependencies = ["strom"]
#
# [tool.uv.sources]
# strom = { path = "..", editable = true }
# ///
"""Example consumer code for the `strom` package. Run: uv run --script examples/simple.py

Checks its own results: exits with 1 and one `FAILED` line on stderr per wrong result, else with 0."""

import asyncio
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from strom import (
    Pools,
    Stage,
    async_stage,
    cpu_stage,
    default_cpu_workers,
    default_io_workers,
    duplicate,
    io_stage,
    product,
    stage,
    stream,
    where,
)


@dataclass(frozen=True)
class Record:
    id: int
    payload: str


@dataclass(frozen=True)
class Score:
    record_id: int
    words: int
    value: int


async def fetch(i: int) -> AsyncIterator[Record]:
    await asyncio.sleep(0.01)
    yield Record(id=i, payload=" ".join(["word"] * (i % 4)))


def parse(r: Record) -> Iterator[tuple[int, list[str]]]:  # top-level -> picklable
    yield r.id, r.payload.split()  # ONE item, which contains a list


def score(parsed: tuple[int, list[str]]) -> Iterator[Score]:
    record_id, words = parsed
    value = sum(i * i for i in range(200_000 + len(words))) % 97
    yield Score(record_id=record_id, words=len(words), value=value)


def render(s: Score) -> Iterator[str]:
    yield f"{s.record_id}:{s.words}:{s.value}"


def append_line(path: Path, line: str) -> Iterator[str]:
    time.sleep(0.01)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    yield line  # what it wrote: an effect stage tells the consumer what it did


# reusable building blocks
ANALYZE: Stage[Record, Score] = (
    cpu_stage(parse, concurrency=2)  # both CPU steps share ONE CPU pool
    | cpu_stage(score, concurrency=4)
)
SCORES: Stage[int, str] = async_stage(fetch, concurrency=8) | ANALYZE | io_stage(render, concurrency=4)
IDS = range(40)  # the inputs of every run: record ids


def split_words(r: Record) -> list[str]:
    return r.payload.split()  # one item per word


def word_list(r: Record) -> Iterator[list[str]]:
    yield r.payload.split()  # ONE item: the list of words


WORDS: Stage[int, str] = async_stage(fetch, concurrency=8) | io_stage(split_words, concurrency=2)


def has_even_id(r: Record) -> bool:
    return r.id % 2 == 0


def describe(pair: tuple[list[str], Score]) -> Iterator[str]:
    words, s = pair
    yield f"{s.record_id}:{len(words)}:{s.value}"


# one Record -> duplicated -> one branch per copy, both at once -> (words, Score); each branch emits one
# item per record, so the product has one pair per record
PAIRS: Stage[int, str] = (
    async_stage(fetch, concurrency=8)
    | where(has_even_id)
    | duplicate()
    | product(io_stage(word_list), ANALYZE)
    | stage(describe)
)


def write_to(path: Path) -> Stage[int, str]:
    return SCORES | io_stage(partial(append_line, path), name="append_line")  # concurrency=1


async def main() -> int:
    """Runs the pipelines on both CPU backends; 0 if every result is as expected, else 1."""
    print(
        f"{sys.version.split()[0]}  GIL enabled: {sys._is_gil_enabled()}  "
        f"default workers: cpu={default_cpu_workers()} io={default_io_workers()}"
    )
    problems: list[str] = []
    for backend in ("process", "thread"):
        out = Path(tempfile.mkdtemp()) / "scores.txt"
        t0 = time.perf_counter()
        async with Pools.open(
            cpu_workers=default_cpu_workers(), io_workers=default_io_workers(), cpu_backend=backend
        ) as pools:  # reused for all runs
            async with stream(SCORES, IDS, pools) as scores:
                collected = [score async for score in scores]  # the consumer folds the outputs: here a list
            num_written = 0
            async with stream(write_to(out), IDS, pools) as written:
                async for _ in written:  # outputs as they come: each line written
                    num_written += 1
            async with stream(WORDS, IDS, pools) as words_out:
                words = [word async for word in words_out]
            async with stream(PAIRS, IDS, pools) as pairs_out:
                pairs = [pair async for pair in pairs_out]
        lines = out.read_text(encoding="utf-8").splitlines()
        print(
            f"{backend:<8} collected={len(collected)} written={len(lines)} words={len(words)} pairs={len(pairs)}  "
            f"{time.perf_counter() - t0:.2f}s"
        )
        expected = {  # what: (expected, got); the output order is not preserved, hence sorted
            "collected scores": (40, len(collected)),
            "written scores (the collected ones)": (sorted(collected), sorted(lines)),
            "lines written, as the consumer counted them": (40, num_written),
            "words (record i has i % 4)": (sum(i % 4 for i in range(40)), len(words)),
            "pairs (one per record with an even id)": (20, len(pairs)),
        }
        problems += [
            f"{what} ({backend} backend): expected {want!r}, got {got!r}"
            for what, (want, got) in expected.items()
            if want != got
        ]
    for problem in problems:
        print(f"FAILED {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # needed for the process backend: its workers import this module
    sys.exit(asyncio.run(main()))
