"""Tests of `strom._runtime.pools`: configuration, lifecycle and reuse of the pools."""

import asyncio
import os
import signal
import subprocess
import sys
import threading
import warnings
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from subprocess import PIPE

import pytest
from helpers import WAIT_LIMIT_TIME, inc, outputs_of, pid_of, run_error

import strom as P
from strom._runtime.pools import _gil_enabled, backends_of
from strom._runtime.thread_backend import ThreadBackend
from strom.backends import StreamingBackend


def crash(item: int) -> list[int]:
    if item == 1:
        os._exit(1)  # kills the worker process
    return [item]


async def test_broken_process_pool_is_replaced(process_pools: P.Pools) -> None:
    with run_error(BrokenProcessPool):
        await outputs_of(P.cpu_stage(crash), range(4), process_pools)
    assert sorted(await outputs_of(P.cpu_stage(inc), range(4), process_pools)) == [1, 2, 3, 4]


async def test_pools_close_runs_releases_still_queued() -> None:
    produced, held_running, held_may_end = threading.Event(), threading.Event(), threading.Event()
    closed_in: list[threading.Thread] = []  # the thread that ran `close`

    class Cursor:  # endless; a closable iterator that is not a generator: garbage collection does not close it
        def __iter__(self) -> Cursor:
            return self

        def __next__(self) -> int:
            produced.set()
            return 1

        def close(self) -> None:
            closed_in.append(threading.current_thread())

    def held(_: None) -> None:
        held_running.set()
        held_may_end.wait(WAIT_LIMIT_TIME)

    async def run_without_consuming(pools: P.Pools) -> None:
        async with P.stream(P.io_stage(lambda _: Cursor(), buffer_size=1), [None], pools):
            await asyncio.Event().wait()  # never set: the run ends when its block is cancelled

    async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
        run_task = asyncio.create_task(run_without_consuming(pools))
        assert await asyncio.to_thread(produced.wait, WAIT_LIMIT_TIME)
        # holds the one io thread: the run's release waits behind it
        holding = asyncio.ensure_future(backends_of(pools).io().run(held, None))
        assert await asyncio.to_thread(held_running.wait, WAIT_LIMIT_TIME)
        run_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run_task
        assert closed_in == []  # the release is queued
        # intentional: `held` ends only once closing the pools has begun, which must not cancel the release
        asyncio.get_running_loop().call_later(0.05, held_may_end.set)
    await holding
    # the release ran as queued, on the thread that holds the iterator; closing the pools waited for it
    assert [thread.name for thread in closed_in] == ["io_0"]


async def test_a_cancelled_close_still_shuts_the_pools_down() -> None:
    release, running = threading.Event(), threading.Event()

    def held(_: None) -> None:
        running.set()
        release.wait(WAIT_LIMIT_TIME)

    opened: list[P.Pools] = []
    backends: list[StreamingBackend] = []
    holding: list[asyncio.Future[None]] = []

    async def open_and_close() -> None:
        async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
            opened.append(pools)
            backends.append(backends_of(pools).io())
            holding.append(asyncio.ensure_future(backends[0].run(held, None)))  # holds the one io thread
            assert await asyncio.to_thread(running.wait, WAIT_LIMIT_TIME)

    close_task = asyncio.create_task(open_and_close())
    async with asyncio.timeout(WAIT_LIMIT_TIME):
        while not (opened and opened[0].closed):  # the close has begun: it waits for `held`
            await asyncio.sleep(0)
    (pool_thread,) = [thread for thread in threading.enumerate() if thread.name == "io_0"]
    close_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await close_task
    assert pool_thread.is_alive()
    release.set()
    # the shutdown goes on in its thread after the cancel: its pool thread ends
    await holding[0]
    await asyncio.to_thread(pool_thread.join, WAIT_LIMIT_TIME)
    assert not pool_thread.is_alive()
    with pytest.raises(RuntimeError, match="closed"):
        await backends[0].run(held, None)


async def test_pools_work_again_after_a_failed_run(pools: P.Pools) -> None:
    failing = threading.Event()

    def fail_on_two_while_others_run(item: int) -> list[int]:  # the other calls are still in flight when it fails
        if item == 2:
            failing.set()
            raise ValueError("boom")
        assert failing.wait(WAIT_LIMIT_TIME)
        return [item]

    with run_error(ValueError, "^boom"):
        await outputs_of(P.io_stage(fail_on_two_while_others_run, concurrency=4), range(20), pools)
    assert len(await outputs_of(P.io_stage(inc, concurrency=4), range(50), pools)) == 50


async def test_pools_open_takes_a_configuration() -> None:
    config = P.PoolConfig(cpu=P.Threads(workers=3, name="cpu"), io=P.Threads(workers=5, name="io"))
    async with P.Pools.open(cpu_workers=3, io_workers=5, cpu_backend="thread") as pools:
        assert pools.config == config
    async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
        assert pools.config.cpu == P.Processes(workers=1)  # the default CPU backend
    async with P.Pools.open() as pools:  # the default sizes follow the hardware
        assert pools.config.cpu == P.Processes(workers=P.default_cpu_workers())
        assert pools.config.io == P.Threads(workers=P.default_io_workers(), name="io")
    with pytest.raises(ValueError, match="cpu_workers"):  # checked at the call, before the block
        P.Pools.open(cpu_workers=0, io_workers=1)
    with pytest.raises(TypeError, match="only inside"):  # no pools that nothing closes
        P.Pools(config)


async def test_pools_using_takes_the_backends() -> None:
    created: list[str] = []

    def io() -> ThreadBackend:  # any callable creating a backend
        created.append("io")
        return P.Threads(workers=2)()

    cpu = P.FromExecutor(factory=lambda: ThreadPoolExecutor(1))
    async with P.Pools.using(cpu=cpu, io=io) as pools:
        assert pools.config == P.PoolConfig(cpu=cpu, io=io)
        assert sorted(await outputs_of(P.io_stage(inc), [1, 2], pools)) == [2, 3]
        assert sorted(await outputs_of(P.io_stage(inc) | P.cpu_stage(inc), [1, 2], pools)) == [3, 4]
    assert created == ["io"]  # once per `Pools`, on first use


def test_thread_backend_with_the_gil_warns_at_the_callers_line() -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread")
        P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="process")
        P.Pools.using(cpu=P.Threads(workers=1), io=P.Threads(workers=1))  # chosen explicitly: no warning
    expected = [__file__] if _gil_enabled() else []  # no warning on the free-threaded build
    assert [(w.category, w.filename) for w in record] == [(RuntimeWarning, f) for f in expected]


async def test_pools_are_created_lazily_and_reset_by_close() -> None:
    async with P.Pools.open(cpu_workers=1, io_workers=2, cpu_backend="thread") as pools:
        assert (pools._cpu, pools._io) == (None, None)
        await outputs_of(P.io_stage(inc), [1], pools)
        assert pools._cpu is None
        assert pools._io is not None
        await outputs_of(P.cpu_stage(inc), [1], pools)
        assert pools._cpu is not None
    assert (pools._cpu, pools._io) == (None, None)


async def test_closed_pools_cannot_be_used_again() -> None:
    created: list[int] = []

    def numbers() -> Iterator[int]:
        created.append(1)
        yield 1

    async with P.Pools.open(cpu_workers=1, io_workers=1, cpu_backend="thread") as pools:
        assert await outputs_of(P.io_stage(inc), numbers(), pools) == [2]
        assert not pools.closed
    assert pools.closed
    with pytest.raises(RuntimeError, match="Pools is closed"):
        await outputs_of(P.io_stage(inc), numbers(), pools)
    with pytest.raises(RuntimeError, match="Pools is closed"):  # also without a pool step
        await outputs_of(P.identity(), numbers(), pools)
    assert len(created) == 1  # checked before the run starts: the inputs were not iterated
    with pytest.raises(RuntimeError, match="Pools is closed"):  # e.g. closed while a run is going on
        backends_of(pools).io()
    with pytest.raises(RuntimeError, match="Pools is closed"):
        backends_of(pools).cpu()
    assert (pools._cpu, pools._io) == (None, None)


async def test_process_pool_is_shared_and_reused_across_runs() -> None:
    async with P.Pools.open(cpu_workers=2, io_workers=2, cpu_backend="process") as pools:
        stage = P.cpu_stage(pid_of, concurrency=4)
        first_pids = set(await outputs_of(stage, range(10), pools))
        second_pids = set(await outputs_of(stage, range(10), pools))
    assert len(first_pids) <= 2
    assert first_pids == second_pids


def test_default_workers_follow_the_hardware() -> None:
    assert P.default_cpu_workers() == (os.process_cpu_count() or 1)
    with ThreadPoolExecutor() as executor:  # the io default is the thread pool's own default
        assert P.default_io_workers() == executor._max_workers


MAIN_SCRIPT = """
import asyncio

import strom as P

def inc(item: int) -> list[int]:
    return [item + 1]

async def main() -> None:
    async with P.Pools.open(cpu_workers=2, io_workers=1, cpu_backend="process") as pools:
        async with P.stream(P.cpu_stage(inc), range(3), pools) as outputs:
            print(sorted([out async for out in outputs]))

if __name__ == "__main__":
    asyncio.run(main())
"""


def test_process_backend_runs_functions_of_the_main_script(tmp_path: Path) -> None:
    """Functions defined in the script being run (module `__main__`) reach the pool workers, which import
    the script again; a subprocess, as pytest itself is `__main__` here."""
    script = tmp_path / "main_script.py"
    script.write_text(MAIN_SCRIPT, encoding="utf-8")
    # its own process group, killed as a whole on timeout: `subprocess.run` would kill only the script and then
    # wait for its pool workers, which keep the output pipes open
    with subprocess.Popen(
        [sys.executable, str(script)], cwd=tmp_path, stdout=PIPE, stderr=PIPE, text=True, start_new_session=True
    ) as process:
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
    assert (process.returncode, stdout) == (0, "[1, 2, 3]\n"), stderr
