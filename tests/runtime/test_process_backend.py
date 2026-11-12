"""Tests of `strom._runtime.process_backend`: what `ProcessBackend` does beyond the contract of every backend
(`test_backends.py`): worker handles in its worker processes (opened by a process on its first use there, closed
by a call pinned to it), crashed workers, and what cannot be pickled.

The pool tasks are top-level functions here (the worker processes import this module); they report their
process, and the `Journal` file shows each process's opens and closes."""

import asyncio
import multiprocessing
import os
import pickle
import signal
import subprocess
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Iterable
from concurrent.futures.process import BrokenProcessPool
from functools import partial
from pathlib import Path
from subprocess import PIPE

import pytest
from helpers import WAIT_LIMIT_TIME, CloseFailure, Failure, Journal

from strom._runtime.process_backend import ProcessBackend
from strom._runtime.worker_handles.process_handles import mark_closed
from strom._runtime.worker_handles.worker_handle import WorkerHandle, using


def pid_with(handle: str, item: int) -> list[int]:
    return [os.getpid()]


def pid_once_released(release: Path, handle: str, item: int) -> list[int]:
    """`pid_with`, once the file `release` exists (up to `WAIT_LIMIT_TIME`): its worker is busy meanwhile."""
    deadline = time.monotonic() + WAIT_LIMIT_TIME
    while not release.exists() and time.monotonic() < deadline:
        time.sleep(0.005)  # intentional: polls for the file the test creates
    return [os.getpid()]


def pid(item: int) -> int:
    return os.getpid()


def logged_pid(log: Path, item: int) -> int:
    with log.open("a") as file:
        file.write(f"{item}\n")
    return os.getpid()


def exit_worker(item: int) -> int:
    os._exit(1)  # kills the worker process, without any cleanup


def close_the_pipe_and_stay(stay_time: float) -> int:
    """Closes every file of its process but the standard streams (as code that makes a daemon of its process
    does), its end of the pipe among them, and lives on for `stay_time`."""
    os.closerange(3, 4096)
    time.sleep(stay_time)  # intentional: a worker that lost its pipe and does not end by itself
    return os.getpid()


def fail(item: int) -> int:
    raise Failure(item)


def unpicklable(item: int) -> Callable[[], int]:
    return lambda: item


class Fussy(Exception):
    """An error that can be pickled but not rebuilt from its pickle (its `__init__` wants two arguments)."""

    def __init__(self, first: int, second: int) -> None:
        super().__init__(f"{first} and {second}")


def fail_fussily(item: int) -> int:
    raise Fussy(item, item)


def listed_in_worker[T](fn: Callable[[int], Iterable[T]], item: int) -> list[T]:
    return list(fn(item))


async def run_using[T](
    backend: ProcessBackend, handle: WorkerHandle[str], fn: Callable[[str, int], Iterable[T]], item: int
) -> list[T]:
    """fn(h, item) with the handle, as one pool task of a `cpu_stage` (listed in the worker)."""
    listed: Callable[[int], list[T]] = partial(listed_in_worker, using(handle, fn))
    return await backend.run(listed, item)


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "journal.log")


@pytest.fixture
async def backend() -> AsyncIterator[ProcessBackend]:
    backend = ProcessBackend(2)
    try:
        yield backend
    finally:
        await backend.aclose()


@pytest.fixture
async def one_worker() -> AsyncIterator[ProcessBackend]:
    """A backend of one worker process: every call runs in it, one after the other."""
    backend = ProcessBackend(1)
    try:
        yield backend
    finally:
        await backend.aclose()


def handle_of(journal: Journal) -> WorkerHandle[str]:
    return WorkerHandle(journal, "journal", uuid.uuid4().hex)


async def opened(journal: Journal, num: int) -> None:
    """Returns once the journal shows `num` opens. Polls it every 5 ms (intentional: the opens happen in other
    processes)."""
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        while len(journal.opens()) < num:
            await asyncio.sleep(0.005)


async def both_workers(backend: ProcessBackend, handle: WorkerHandle[str], journal: Journal) -> set[int]:
    """Opens the handle in both worker processes: two calls at once, each held until both have opened it."""
    release = journal.path.with_name(f"release-{uuid.uuid4().hex}")
    held = partial(pid_once_released, release)
    calls = [asyncio.ensure_future(run_using(backend, handle, held, 0)) for _ in range(2)]
    await opened(journal, 2)
    release.touch()
    return {pid for (pid,) in await asyncio.gather(*calls)}


async def test_a_handle_opens_once_per_worker_process_and_closes_in_an_idle_one_at_once(
    backend: ProcessBackend, journal: Journal
) -> None:
    handle = handle_of(journal)
    pids = await both_workers(backend, handle, journal)
    assert len(pids) == 2 and journal.pids() == pids and os.getpid() not in pids
    await run_using(backend, handle, pid_with, 0)  # open already: no third open
    assert len(journal.opens()) == 2 and journal.closes() == []
    await asyncio.wait_for(backend.close_handle(handle.key), WAIT_LIMIT_TIME)  # both workers are idle
    assert sorted(journal.closes()) == sorted(journal.opens())


async def test_a_busy_worker_closes_its_handle_after_the_call_it_runs(
    backend: ProcessBackend, journal: Journal, tmp_path: Path
) -> None:
    handle = handle_of(journal)
    release = tmp_path / "release"
    running = asyncio.ensure_future(run_using(backend, handle, partial(pid_once_released, release), 0))
    await opened(journal, 1)  # the call runs
    closing = asyncio.ensure_future(backend.close_handle(handle.key))
    await asyncio.sleep(0.05)  # intentional: a close that did not wait for the call would be done by now
    assert not closing.done() and journal.closes() == []
    release.touch()
    await asyncio.wait_for(closing, WAIT_LIMIT_TIME)
    assert (await running)[0] in journal.pids()
    assert journal.closes() == journal.opens()


async def test_the_errors_of_the_closes_come_with_their_process(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.log", failing_close=True)
    backend = ProcessBackend(2)
    try:
        handle = handle_of(journal)
        pids = await both_workers(backend, handle, journal)
        with pytest.raises(BaseExceptionGroup) as info:
            await backend.close_handle(handle.key)
        errors = info.value.exceptions
        assert all(isinstance(error, CloseFailure) for error in errors)
        assert sorted(note for error in errors for note in error.__notes__) == sorted(
            f"in process {pid}" for pid in pids
        )
    finally:
        await backend.aclose()


async def test_a_call_using_a_closed_handle_fails_before_it_reaches_a_worker(
    one_worker: ProcessBackend, journal: Journal
) -> None:
    handle = handle_of(journal)
    worker = await one_worker.run(pid, 0)
    mark_closed(handle.key)  # as the end of its block does, before it closes it in the workers
    await one_worker.close_handle(handle.key)
    with pytest.raises(RuntimeError, match="worker handle 'journal' is closed"):
        await run_using(one_worker, handle, pid_with, 0)  # refused when it is pickled for its worker
    assert await one_worker.run(pid, 0) == worker  # the worker lives on
    assert journal.opens() == []


async def test_a_crashed_worker_fails_its_call_and_is_replaced_while_the_other_goes_on(
    backend: ProcessBackend, journal: Journal, tmp_path: Path
) -> None:
    handle = handle_of(journal)
    release = tmp_path / "release"
    other = asyncio.ensure_future(run_using(backend, handle, partial(pid_once_released, release), 0))
    await opened(journal, 1)  # the other worker runs its call
    with pytest.raises(BrokenProcessPool):
        await backend.run(exit_worker, 0)
    replaced = await backend.run(pid, 0)  # the same pool thread, a new process
    release.touch()
    (survivor,) = await other
    assert replaced != survivor and survivor in journal.pids()


def has_ended(process: int) -> bool:
    """Whether the process has ended (Linux): it is gone, or a zombie its parent has not waited for yet. Its
    files, and so its end of a pipe, are closed then."""
    try:
        stat = Path(f"/proc/{process}/stat").read_text(encoding="utf-8")
    except FileNotFoundError, ProcessLookupError:
        return True
    return stat.rpartition(")")[2].split()[0] == "Z"


async def ended(process: int) -> None:
    """Returns once the process has ended. Polls every 5 ms (intentional: the state of another process)."""
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        while not has_ended(process):
            await asyncio.sleep(0.005)


async def test_a_worker_that_ended_while_idle_is_replaced_without_a_failure(one_worker: ProcessBackend) -> None:
    worker = await one_worker.run(pid, 0)
    os.kill(worker, signal.SIGKILL)  # while it is idle: as the out-of-memory killer does
    await ended(worker)
    replaced = await one_worker.run(pid, 0)  # it ran nothing, so nothing fails: another process takes the call
    assert replaced != worker
    assert await one_worker.run(pid, 0) == replaced


async def test_a_worker_that_lost_its_pipe_is_ended_and_replaced(one_worker: ProcessBackend) -> None:
    worker = await one_worker.run(pid, 0)
    with pytest.raises(BrokenProcessPool):  # at once: nothing waits for a process that can no longer answer
        await asyncio.wait_for(one_worker.run(close_the_pipe_and_stay, 2 * WAIT_LIMIT_TIME), WAIT_LIMIT_TIME)
    await ended(worker)
    assert await one_worker.run(pid, 0) != worker


async def test_a_handle_of_a_crashed_worker_counts_as_closed(one_worker: ProcessBackend, journal: Journal) -> None:
    handle = handle_of(journal)
    await run_using(one_worker, handle, pid_with, 0)
    with pytest.raises(BrokenProcessPool):
        await one_worker.run(exit_worker, 0)
    await asyncio.wait_for(one_worker.close_handle(handle.key), WAIT_LIMIT_TIME)  # nothing to wait for
    assert len(journal.opens()) == 1 and journal.closes() == []  # it died with its process


async def test_closing_a_handle_starts_no_process_for_a_worker_that_ended_while_idle(
    one_worker: ProcessBackend, journal: Journal
) -> None:
    children = {child.pid for child in multiprocessing.active_children()}
    handle = handle_of(journal)
    (worker,) = await run_using(one_worker, handle, pid_with, 0)
    os.kill(worker, signal.SIGKILL)
    await ended(worker)
    await asyncio.wait_for(one_worker.close_handle(handle.key), WAIT_LIMIT_TIME)
    assert {child.pid for child in multiprocessing.active_children()} <= children  # none took its place for that
    assert len(journal.opens()) == 1 and journal.closes() == []  # it died with its process


async def test_a_worker_process_closes_the_handles_it_still_holds_when_the_backend_closes(journal: Journal) -> None:
    backend = ProcessBackend(1)
    handle = handle_of(journal)
    await run_using(backend, handle, pid_with, 0)
    assert journal.closes() == []
    await backend.aclose()  # waits for the process, which closes what is left at its end
    assert journal.closes() == journal.opens()


async def test_a_cancelled_call_that_waits_for_a_worker_never_starts(
    one_worker: ProcessBackend, journal: Journal, tmp_path: Path
) -> None:
    release, log = tmp_path / "release", tmp_path / "ran.log"
    first = asyncio.ensure_future(run_using(one_worker, handle_of(journal), partial(pid_once_released, release), 0))
    second = asyncio.ensure_future(one_worker.run(partial(logged_pid, log), 2))  # waits in this process
    await opened(journal, 1)  # the first call runs, the second is queued behind it
    second.cancel()
    with pytest.raises(asyncio.CancelledError):
        await second
    release.touch()
    (worker,) = await first
    assert await one_worker.run(partial(logged_pid, log), 3) == worker
    assert log.read_text().split() == ["3"]


async def test_an_error_arrives_as_itself_with_the_workers_traceback_as_its_cause(backend: ProcessBackend) -> None:
    with pytest.raises(Failure) as info:
        await backend.run(fail, 7)
    assert info.value.args == (7,)
    assert "in fail" in str(info.value.__cause__) and "raise Failure(item)" in str(info.value.__cause__)


async def test_what_cannot_be_pickled_fails_its_own_call_only(one_worker: ProcessBackend) -> None:
    worker = await one_worker.run(pid, 0)
    with pytest.raises((pickle.PicklingError, AttributeError)):  # the call: refused in this process
        await one_worker.run(lambda item: item, 0)
    with pytest.raises((pickle.PicklingError, AttributeError)):  # the result: the worker's error
        await one_worker.run(unpicklable, 0)
    with pytest.raises(RuntimeError, match=r"^Fussy: 7 and 7") as info:  # an error this process could not rebuild
        await one_worker.run(fail_fussily, 7)
    assert "raise Fussy(item, item)" in str(info.value.__cause__)
    assert await one_worker.run(pid, 0) == worker  # the worker lives on, in step with its pipe


def exit_code_of_a_child(item: int) -> int | None:
    """Starts a process of its own, as a function using `multiprocessing` (or joblib) does."""
    child = multiprocessing.Process(target=pid, args=(item,))
    child.start()
    child.join(WAIT_LIMIT_TIME)
    return child.exitcode


async def test_a_worker_process_may_start_processes_of_its_own(one_worker: ProcessBackend) -> None:
    assert await one_worker.run(exit_code_of_a_child, 0) == 0  # a daemon could not: "not allowed to have children"


NEVER_CLOSED = """
import asyncio
import os

from strom._runtime.process_backend import ProcessBackend


def pid(item):
    return os.getpid()


async def main():
    backend = ProcessBackend(2)  # never closed
    print(*await asyncio.gather(backend.run(pid, 0), backend.run(pid, 0)))


if __name__ == "__main__":
    asyncio.run(main())
"""


def test_the_worker_processes_of_a_backend_that_was_never_closed_end_with_the_interpreter(tmp_path: Path) -> None:
    """Nothing closed them: the exit must neither wait for them nor leave them behind."""
    script = tmp_path / "never_closed.py"
    script.write_text(NEVER_CLOSED, encoding="utf-8")
    # its own process group, killed as a whole on timeout (as in `test_pools.py`)
    with subprocess.Popen(
        [sys.executable, str(script)], cwd=tmp_path, stdout=PIPE, stderr=PIPE, text=True, start_new_session=True
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    assert process.returncode == 0, stderr
    workers = [int(worker) for worker in stdout.split()]
    assert len(workers) == 2
    deadline = time.monotonic() + WAIT_LIMIT_TIME
    while not all(has_ended(worker) for worker in workers):
        assert time.monotonic() < deadline, "a worker process outlived its parent"
        time.sleep(0.01)  # intentional: polls for the end of the terminated processes
