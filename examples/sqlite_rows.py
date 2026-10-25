# /// script
# requires-python = ">=3.14"
# dependencies = ["strom", "sqlalchemy>=2.1,<2.2"]
#
# [tool.uv.sources]
# strom = { path = "..", editable = true }
# ///
"""Worker handles: a SQLAlchemy engine on a sqlite3 database, and a model, each opened once per process and
closed at the end of its block. Run: uv run --script examples/sqlite_rows.py

One engine (with its connection pool) is shared by a read and a write stage on the "io" threads; each input
checks out a connection of its own and commits its transaction before it emits. A model-like handle, slow to
load, is opened once in each "cpu" worker process that scores. Checks its own results: exits with 1 and one
`FAILED` line on stderr per wrong result, else with 0."""

import asyncio
import os
import sqlite3
import sys
import tempfile
import time
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from sqlalchemy import Engine, create_engine, text

from strom import Pools, Stage, cpu_stage, io_stage, stream, using, worker_handle

SENSORS = [f"sensor-{num}" for num in range(12)]
READINGS_PER_SENSOR = 25
CPU_WORKERS = 2
IO_WORKERS = 4
CONCURRENCY = 4  # per io step: the engine lends up to 2 * CONCURRENCY connections at once (no checkout waits)


def log(path: Path, line: str) -> None:
    """Appends a line to the handle log, which shows where each handle opened and closed."""
    with path.open("a", encoding="utf-8") as file:
        file.write(f"{line} {os.getpid()}\n")


# ---- the handles: openers (context managers), top-level so that worker processes can import them
@contextmanager
def engine_of(database: Path, handle_log: Path) -> Generator[Engine]:
    """One engine per process: a pool of connections that every thread checks out from, per input."""
    engine = create_engine(
        f"sqlite:///{database}",
        connect_args={"timeout": 5},  # bound every wait: a write waits at most 5 s for the database lock
        pool_size=2 * CONCURRENCY,  # both io steps' inputs in flight at once
        pool_timeout=5,
    )
    log(handle_log, "open engine")
    try:
        yield engine
    finally:
        engine.dispose()
        log(handle_log, "close engine")


@dataclass(frozen=True)
class Model:
    """Stands in for a loaded model: read-only once loaded, so the threads of a process may share it."""

    weights: tuple[float, ...]

    def score(self, values: list[float]) -> float:
        return sum(weight * value for weight, value in zip(self.weights, sorted(values), strict=False))


@contextmanager
def scoring_model(handle_log: Path) -> Generator[Model]:
    time.sleep(0.2)  # loading takes a while: once per worker process, not per input
    log(handle_log, "open model")
    try:
        yield Model(weights=tuple(1.0 / (1 + num) for num in range(READINGS_PER_SENSOR)))
    finally:
        log(handle_log, "close model")


# ---- the stage functions: the handle first, then the input
def readings_of(engine: Engine, sensor: str) -> Iterator[tuple[str, list[float]]]:
    with engine.connect() as conn:  # a connection per input, back to the pool at the end of the block
        values = [
            row.value for row in conn.execute(text("SELECT value FROM readings WHERE sensor = :s"), {"s": sensor})
        ]
    yield sensor, values  # emitted after the connection is back


def score(model: Model, readings: tuple[str, list[float]]) -> Iterator[tuple[str, float]]:
    sensor, values = readings
    yield sensor, model.score(values)


def store(engine: Engine, scored: tuple[str, float]) -> Iterator[str]:
    sensor, value = scored
    with engine.begin() as conn:  # a transaction per input: committed at the end of the block
        conn.execute(text("INSERT INTO scores (sensor, score) VALUES (:s, :v)"), {"s": sensor, "v": value})
    yield sensor  # only once it is committed


# ---- setup, and the expected results without strom
def create_database(database: Path) -> None:
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # readers do not wait for the writers
        conn.execute("CREATE TABLE readings (sensor TEXT, value REAL)")
        conn.execute("CREATE TABLE scores (sensor TEXT PRIMARY KEY, score REAL)")
        conn.executemany(
            "INSERT INTO readings VALUES (?, ?)",
            [(sensor, float((num * 7 + len(sensor)) % 11)) for sensor in SENSORS for num in range(READINGS_PER_SENSOR)],
        )
    conn.close()


def expected_scores(database: Path) -> dict[str, float]:
    model = Model(weights=tuple(1.0 / (1 + num) for num in range(READINGS_PER_SENSOR)))
    with sqlite3.connect(database) as conn:
        rows = conn.execute("SELECT sensor, value FROM readings").fetchall()
    conn.close()
    return {sensor: model.score([value for name, value in rows if name == sensor]) for sensor in SENSORS}


def stored_scores(database: Path) -> dict[str, float]:
    with sqlite3.connect(database) as conn:
        rows = conn.execute("SELECT sensor, score FROM scores").fetchall()
    conn.close()
    return dict(rows)


async def main() -> int:
    """Scores every sensor's readings and stores the scores; 0 if every result is as expected, else 1."""
    directory = Path(tempfile.mkdtemp())
    database, handle_log = directory / "readings.db", directory / "handles.log"
    create_database(database)
    async with (
        Pools.open(cpu_workers=CPU_WORKERS, io_workers=IO_WORKERS) as pools,  # "cpu": processes
        worker_handle(partial(engine_of, database, handle_log), pools, name="engine") as db,
        worker_handle(partial(scoring_model, handle_log), pools, name="model") as model,
    ):
        pipeline: Stage[str, str] = (
            io_stage(using(db, readings_of), concurrency=CONCURRENCY)
            | cpu_stage(using(model, score), concurrency=CPU_WORKERS)
            | io_stage(using(db, store), concurrency=CONCURRENCY)
        )
        print(pipeline)
        async with stream(pipeline, SENSORS, pools) as outputs:
            stored = [sensor async for sensor in outputs]
        open_while_running = handle_log.read_text(encoding="utf-8").splitlines()
    # the blocks have ended: every handle is closed, in every process that opened it
    events = [line.split() for line in handle_log.read_text(encoding="utf-8").splitlines()]
    opened = sorted((name, pid) for verb, name, pid in events if verb == "open")
    closed = sorted((name, pid) for verb, name, pid in events if verb == "close")
    engines = [pid for name, pid in opened if name == "engine"]
    models = [pid for name, pid in opened if name == "model"]
    print(f"stored {len(stored)} scores; engines opened in {engines}, models in {models}; closed: {len(closed)}")
    scores, want_scores = stored_scores(database), expected_scores(database)
    expected = {  # what: (expected, got)
        "stored sensors": (sorted(SENSORS), sorted(stored)),
        "scores in the database": (want_scores, {sensor: scores.get(sensor) for sensor in want_scores}),
        "engines: one, in this process (the io threads share it)": ([str(os.getpid())], engines),
        "models: one per worker process that scored, not in this process": (
            True,
            1 <= len(models) <= CPU_WORKERS and len(set(models)) == len(models) and str(os.getpid()) not in models,
        ),
        "nothing closed while the blocks lasted": (
            [],
            [line for line in open_while_running if line.startswith("close")],
        ),
        "every handle closed where it was opened": (opened, closed),
    }
    problems = [f"{what}: expected {want!r}, got {got!r}" for what, (want, got) in expected.items() if want != got]
    for problem in problems:
        print(f"FAILED {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":  # needed for the process backend: its workers import this module
    sys.exit(asyncio.run(main()))
