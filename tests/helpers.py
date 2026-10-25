"""Helpers shared by the test modules: user functions, sum tags, failures, trackers of concurrent calls,
and runs with temporary pools.

Naming (besides the conventions in `ARCHITECTURE.md`): user functions take `item`, lambdas full
parameter names; helpers are named by their effect (`dup`: item -> [item, item], `sleep_10ms`).
`TRACK` is replaced for every test (`tests/conftest.py`): test modules read it as `helpers.TRACK`."""

import asyncio
import contextlib
import itertools
import os
import pickle
import threading
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterable, AsyncIterator, Callable, Generator, Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast, override

import pytest

import strom as P
from strom import testing
from strom._interpreters.failures import _RUN_FAILED
from strom._runtime import iterator_registry
from strom.backends import (
    StreamingBackend,
    WorkerId,
    close_process_handle,
    init_handles,
    init_worker,
    release_scope,
)
from strom.metrics import Event, Recorder, RunFinished, RunStarted, RunStats, StatsRecorder

bag = testing.bag
meaning = testing.evaluate  # the reference semantics; `meaning_async` inside a running loop
meaning_async = testing.evaluate_async

ROOT = Path(__file__).resolve().parent.parent


def inc(item: int) -> list[int]:
    return [item + 1]


def neg(item: int) -> list[int]:
    return [-item]


def double(item: int) -> list[int]:
    return [2 * item]


def many(item: int) -> list[int]:
    return list(range(item))


def repeat(item: int, times: int) -> list[int]:
    return [item] * times


def is_odd(item: int) -> bool:
    return item % 2 == 1


def at_most_three(item: int) -> list[int]:
    return list(range(abs(item) % 4))  # bounded expansion: generated pipelines stay small


def at_most_three_lazily(item: int) -> Iterator[int]:
    yield from at_most_three(item)


async def async_at_most_three(item: int) -> AsyncIterator[int]:
    """`at_most_three`, yielding to the event loop before each output so that concurrent calls
    interleave."""
    for out in at_most_three(item):
        await asyncio.sleep(0)
        yield out


def add_pair(pair: tuple[int, int]) -> list[int]:
    return [pair[0] + pair[1]]


type Tagged = P.Left[int] | P.Right[int]


def tagged_items() -> list[Tagged]:
    return [P.Left(1), P.Right(2), P.Left(3)]


def tagged_pairs() -> list[tuple[Tagged, int]]:
    return [(P.Left(2), 0), (P.Right(2), 0)]


def to_right(item: int) -> list[P.Right[int]]:
    return [P.Right(item)]


def countdown_from(item: int) -> Iterator[P.Left[int] | P.Right[int]]:
    """Emits the item and feeds back the next smaller one: iterated, item, item - 1, ..., 0."""
    yield P.Right(item)
    if item > 0:
        yield P.Left(item - 1)


type Countdown = tuple[int, int]
"""An item and how many more times a loop's body feeds it back."""


def with_depth(item: int) -> list[Countdown]:
    # at most one feedback: generated stages fan out up to about 81 outputs (nested `product`), and each
    # feedback multiplies that (two took minutes per example)
    return [(item, abs(item) % 2)]


def count_down(countdown: Countdown) -> list[P.Left[Countdown] | P.Right[int]]:
    """Feeds the item back while its depth lasts, then emits it."""
    item, depth = countdown
    return [P.Left((item, depth - 1))] if depth > 0 else [P.Right(item)]


def countdown_body(stage: P.Stage[int, int]) -> P.Stage[Countdown, P.Left[Countdown] | P.Right[int]]:
    """Applies `stage` to the item and feeds it back while its depth lasts."""
    lifted: P.Stage[Countdown, Countdown] = P.first(stage)
    return lifted | P.stage(count_down)


def slow_double(item: int) -> list[int]:
    """Sleeps briefly, so that the buffers in front of it fill up (backpressure)."""
    time.sleep(0.0005)
    return [2 * item]


async def async_inc(item: int) -> AsyncIterator[int]:
    """Yields to the event loop once, so that concurrent calls interleave."""
    await asyncio.sleep(0)
    yield item + 1


def text(item: object) -> list[str]:
    return [str(item)]


class Failure(Exception):
    """The user's own error."""


def fail_on_7(item: int) -> list[int]:
    if item == 7:
        raise Failure(item)
    return [item]


def boom(item: int) -> list[int]:
    if item == 2:
        raise ValueError("boom")
    return [item]


def explode(item: int) -> list[int]:
    raise ValueError("stage failed")


class RecorderFailure(Exception):
    """An error of a recorder."""


def raising_on(kind: type[Event], step_name: str) -> Recorder:
    """A recorder failing on events of `kind`: run events, or events of the step `step_name`."""

    def record(event: Event) -> None:
        match event:
            case RunStarted() | RunFinished():
                concerned = True
            case _:
                concerned = event.step_id.name == step_name
        if concerned and isinstance(event, kind):
            raise RecorderFailure(kind.__name__)

    return record


def pid_of(item: int) -> list[int]:
    """The process id of the pool worker running it. Sleeps 5 ms, so that concurrent calls overlap
    and spread over the pool workers, and so that a running time can be measured."""
    time.sleep(0.005)
    return [os.getpid()]


def sleep_10ms(item: int) -> list[int]:
    """Takes 10 ms without using CPU: a measurable running time and a slow step (bottleneck)."""
    time.sleep(0.01)
    return [item]


SATURATION_GRACE_TIME = 0.05  # seconds in which a call above a limit would still get in


WAIT_LIMIT_TIME = 5.0  # upper bound of every wait in these helpers; only reached when a test fails


class Tracker:
    """Counts the calls and the maximum number of calls inside a function at once, per tag (thread-safe).

    Calls do not sleep to overlap. `saturating` holds them inside the function until a limit is
    reached, so the maximum does not depend on timing."""

    def __init__(self) -> None:
        self.changed = threading.Condition()
        self.num_active: Counter[str] = Counter()
        self.num_max_active: Counter[str] = Counter()
        self.num_calls: Counter[str] = Counter()
        self.held: dict[str, threading.Event] = {}  # tag -> gate: its calls leave when the gate is open

    def run(self, tag: str, item: int) -> int:
        with self.changed:
            self.num_active[tag] += 1
            self.num_calls[tag] += 1
            self.num_max_active[tag] = max(self.num_max_active[tag], self.num_active[tag])
            self.changed.notify_all()
        if (gate := self.held.get(tag)) is not None:
            gate.wait(WAIT_LIMIT_TIME)
        with self.changed:
            self.num_active[tag] -= 1
        return item

    @contextmanager
    def saturating(self, *groups: Mapping[str, int]) -> Generator[None]:
        """Holds the calls of every tag in a group until all tags of the group have the given number of
        calls inside at once, waits `SATURATION_GRACE_TIME` for calls above a limit, then lets the group
        go.

        Groups are released one after the other when a later step only gets items from an earlier one.
        If a limit is never reached the group is released after `WAIT_LIMIT_TIME` and the test's assertion
        on `num_max_active` fails."""
        gates = [threading.Event() for _ in groups]

        def release_when_saturated(group: Mapping[str, int], gate: threading.Event) -> None:
            with self.changed:
                self.changed.wait_for(
                    lambda: all(self.num_active[tag] >= limit for tag, limit in group.items()), WAIT_LIMIT_TIME
                )
            time.sleep(SATURATION_GRACE_TIME)
            gate.set()

        for group, gate in zip(groups, gates, strict=True):
            self.held.update(dict.fromkeys(group, gate))
        for group, gate in zip(groups, gates, strict=True):
            threading.Thread(target=release_when_saturated, args=(group, gate), daemon=True).start()
        try:
            yield
        finally:
            for gate in gates:
                gate.set()


TRACK = Tracker()


def tracked_a(item: int) -> list[int]:
    return [TRACK.run("a", item)]


def tracked_b(item: int) -> list[int]:
    return [TRACK.run("b", item)]


class CountingThreads(StreamingBackend):
    """The thread backend, counting the pool tasks submitted to it, so that a test can wait until they are
    queued. Its own config: `Pools.using(io=CountingThreads(workers=1))`."""

    def __init__(self, workers: int) -> None:
        self._threads = P.Threads(workers=workers)()
        self.submitted = threading.Condition()
        self.num_submitted = 0

    def __call__(self) -> CountingThreads:
        return self

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A, *, affinity: WorkerId | None = None) -> B:
        # started eagerly: its first step submits the pool task, so the count is never ahead of the queue
        running = asyncio.Task(self._threads.run(fn, arg, affinity=affinity), eager_start=True)
        with self.submitted:
            self.num_submitted += 1
            self.submitted.notify_all()
        try:
            return await running
        except BaseException:
            running.cancel()
            raise

    @override
    def release(self, scope: str) -> None:
        self._threads.release(scope)

    @override
    async def aclose(self) -> None:
        await self._threads.aclose()

    def wait_until_submitted(self, num: int) -> bool:
        with self.submitted:
            return self.submitted.wait_for(lambda: self.num_submitted >= num, WAIT_LIMIT_TIME)


# ------------------------------------------------------- a backend without shared memory (test-only)
def _in_worker(payload: bytes) -> bytes:
    """Executed in a worker of a `PicklingBackend`: the pickled call, its result or its error pickled back
    (an error that cannot be pickled as a stand-in naming it)."""
    fn, arg = cast("tuple[Callable[[object], object], object]", pickle.loads(payload))  # noqa: S301 (own data)
    try:
        return pickle.dumps((True, fn(arg)))
    except Exception as error:
        try:
            return pickle.dumps((False, error))
        except Exception:
            return pickle.dumps((False, RuntimeError(f"unpicklable {type(error).__name__}: {error}")))


class PicklingBackend(StreamingBackend):
    """A backend that behaves like a remote one, built on the interface for implementers only: several
    single-thread workers, each with a `WorkerId` and an iterator registry of its own; every function,
    argument, result and error is pickled; `affinity` routes a call to its worker, None takes turns. So a
    call routed to the wrong worker fails, and so does anything that relies on shared memory.

    A release goes to every worker, behind the calls already there (each runs its calls in order). Closing
    runs the releases still queued (it waits for every queued pool task: those of finished runs were
    cancelled already). `registries`: the workers' registries, to check that none keeps an iterator."""

    def __init__(self, num_workers: int) -> None:
        self.registries: list[iterator_registry._Registry] = []
        self._lock = threading.Lock()
        token = uuid.uuid4().hex
        self._workers = {
            WorkerId(f"{token}-{num}"): ThreadPoolExecutor(
                1,
                thread_name_prefix=f"pickling-{num}",
                initializer=self._init_worker,
                initargs=(WorkerId(f"{token}-{num}"),),
            )
            for num in range(num_workers)
        }
        self._turns = itertools.cycle(list(self._workers.values()))

    def _init_worker(self, worker_id: WorkerId) -> None:
        init_worker(worker_id)
        init_handles()
        with self._lock:
            self.registries.append(iterator_registry._current_registry())

    def num_registered(self) -> int:
        return sum(len(registry.iterators) for registry in self.registries)

    def _executor(self, affinity: WorkerId | None) -> ThreadPoolExecutor:
        if affinity is None:
            return next(self._turns)
        executor = self._workers.get(affinity)
        if executor is None:
            raise LookupError(f"no worker {affinity}: lost")
        return executor

    @override
    async def run[A, B](self, fn: Callable[[A], B], arg: A, *, affinity: WorkerId | None = None) -> B:
        data = await asyncio.wrap_future(self._executor(affinity).submit(_in_worker, pickle.dumps((fn, arg))))
        ok, value = cast("tuple[bool, B]", pickle.loads(data))  # noqa: S301 (own data)
        if ok:
            return value
        raise cast("Exception", value)

    @override
    def release(self, scope: str) -> None:
        payload = pickle.dumps((release_scope, scope))
        for executor in self._workers.values():
            executor.submit(_in_worker, payload)

    @override
    async def close_handle(self, key: str) -> None:
        """`close_process_handle` on each worker, as a remote backend would in each of its processes (here they
        share this process's table, which the handle's block closes too: a second close is a no-op)."""
        results = await asyncio.gather(
            *(self.run(close_process_handle, key, affinity=worker) for worker in self._workers),
            return_exceptions=True,
        )
        errors = [result for result in results if isinstance(result, BaseException)]
        if errors:
            raise BaseExceptionGroup("closing the worker handle failed on the workers", errors)

    @override
    async def aclose(self) -> None:
        await asyncio.to_thread(self._shut_down)

    def _shut_down(self) -> None:
        for executor in self._workers.values():
            executor.shutdown()


@dataclass
class Pickling:
    """Creates a `PicklingBackend` of `workers` workers per call and keeps them (`created`) for checks."""

    workers: int = 2
    created: list[PicklingBackend] = field(default_factory=list)

    def __call__(self) -> PicklingBackend:
        backend = PicklingBackend(self.workers)
        self.created.append(backend)
        return backend

    def num_registered(self) -> int:
        """The iterators the created backends' workers still hold."""
        return sum(backend.num_registered() for backend in self.created)


def collect_pickling[I, O](stage: P.Stage[I, O], inputs: Iterable[I], recorder: Recorder | None = None) -> list[O]:
    """`collect` on `PicklingBackend`s for both resources, in a loop of its own; checks that no worker keeps
    an iterator once the pools are closed."""
    cpu, io = Pickling(), Pickling()

    async def run() -> list[O]:
        async with P.Pools.using(cpu=cpu, io=io) as pools:
            return await outputs_of(stage, inputs, pools, recorder=recorder)

    try:
        return asyncio.run(run())
    finally:
        assert cpu.num_registered() == io.num_registered() == 0


def run_error[E: BaseException](kind: type[E], match: str | None = None) -> pytest.RaisesGroup[E]:
    """Expects a failed run: its group (always one, see the `strom` module docstring) holds exactly
    one error, of `kind`, matching `match` (its message and notes)."""
    return pytest.RaisesGroup(
        pytest.RaisesExc(kind, match=match),
        match=f"^{_RUN_FAILED}$",
        check=lambda group: isinstance(group, P.RunFailed),
    )


async def outputs_of[I, O](
    stage: P.Stage[I, O],
    inputs: Iterable[I] | AsyncIterable[I],
    pools: P.Pools,
    *,
    recorder: Recorder | None = None,
) -> list[O]:
    """The outputs of a run of `stage` on `inputs`, as a list (in the order they came)."""
    async with P.stream(stage, inputs, pools, recorder=recorder) as outputs:
        return [out async for out in outputs]


def _run_alone[I, O](
    stage: P.Stage[I, O],
    inputs: Iterable[I],
    io_workers: int,
    cpu_backend: P.CpuBackendKind,
    recorder: Recorder | None = None,
) -> list[O]:
    """A run in an event loop of its own, with temporary pools; they are closed (all their tasks finished)
    on return. For sync tests, e.g. the Hypothesis tests."""

    async def run() -> list[O]:
        async with P.Pools.open(cpu_workers=2, io_workers=io_workers, cpu_backend=cpu_backend) as pools:
            return await outputs_of(stage, inputs, pools, recorder=recorder)

    return asyncio.run(run())


def collect[I, O](
    stage: P.Stage[I, O],
    inputs: Iterable[I],
    io_workers: int = 8,
    cpu_backend: P.CpuBackendKind = "thread",
    recorder: Recorder | None = None,
) -> list[O]:
    """The outputs of a run of `stage` on `inputs` (see `_run_alone`)."""
    return _run_alone(stage, inputs, io_workers, cpu_backend, recorder)


# ------------------------------------------------------- worker handles
class CloseFailure(Exception):
    """The error of a handle's close."""


class OpenFailure(Exception):
    """The error of an opener."""


@dataclass(frozen=True)
class Journal:
    """An opener (picklable, for threads and worker processes alike) that logs its opens and closes to the file
    `path`, one line each: `open <pid> <token>`, `close <pid> <token>`, `failed <pid>`. Its handle is the token,
    unique per open.

    `failing_opens`: that many opens fail first (counted in the file); `failing_close`: its close raises.
    `open_time`: an open takes that long (seconds), so that concurrent first uses overlap."""

    path: Path
    failing_opens: int = 0
    failing_close: bool = False
    open_time: float = 0.0

    def __call__(self) -> contextlib.AbstractContextManager[str]:
        return _journaled(self)

    def log(self, line: str) -> None:
        with self.path.open("a") as file:  # one short write per line (O_APPEND): lines never interleave
            file.write(f"{line}\n")

    def lines(self) -> list[list[str]]:
        """The logged lines, split into words."""
        return [line.split() for line in self.path.read_text().splitlines()] if self.path.exists() else []

    def opens(self) -> list[str]:
        """The tokens opened, in order."""
        return [words[2] for words in self.lines() if words[0] == "open"]

    def closes(self) -> list[str]:
        return [words[2] for words in self.lines() if words[0] == "close"]

    def pids(self) -> set[int]:
        """The processes that opened a handle."""
        return {int(words[1]) for words in self.lines() if words[0] == "open"}


@contextmanager
def _journaled(journal: Journal) -> Generator[str]:
    """Logs the open (or, while `failing_opens` lasts, fails it), yields a new token, logs the close."""
    if journal.open_time:
        time.sleep(journal.open_time)  # intentional: concurrent first uses must overlap (see `Journal`)
    if sum(words[0] == "failed" for words in journal.lines()) < journal.failing_opens:
        journal.log(f"failed {os.getpid()}")
        raise OpenFailure("cannot open")
    token = uuid.uuid4().hex[:8]
    journal.log(f"open {os.getpid()} {token}")
    try:
        yield token
    finally:
        journal.log(f"close {os.getpid()} {token}")
        if journal.failing_close:
            raise CloseFailure(f"cannot close {token}")


def tokens_of(handle: str, item: int) -> list[str]:
    """The handle's token, once per input: what a stage using a `Journal` handle emits."""
    return [handle]


def tokens_lazily(handle: str, item: int) -> Iterator[str]:
    """`tokens_of`, `item` times, as a generator (a use stays in flight while it is suspended)."""
    for _ in range(item):
        yield handle


class FailingLines:
    """A closable iterator (like a file) whose second `next` fails."""

    def __init__(self) -> None:
        self.closed = False
        self.num_calls = 0

    def __iter__(self) -> FailingLines:
        return self

    def __next__(self) -> int:
        self.num_calls += 1
        if self.num_calls == 2:
            raise ValueError("cannot read")
        return self.num_calls

    def close(self) -> None:
        self.closed = True


def dup(item: int) -> list[int]:
    return repeat(item, 2)


def stats_of[I](
    stage: P.Stage[I, object], inputs: Iterable[I], io_workers: int = 8, cpu_backend: P.CpuBackendKind = "thread"
) -> tuple[list[object], RunStats]:
    """The outputs and the statistics of a run (see `_run_alone`)."""
    recorder = StatsRecorder()
    outputs = _run_alone(stage, inputs, io_workers, cpu_backend, recorder)
    return outputs, recorder.stats()
