"""Tests of `strom._runtime.worker_handles.worker_handle`: worker handles through the public API (`worker_handle`,
`using`), one per process on the pools that share them, opened on their first use, closed at the end of their
block; per input where no pool shares them (the reference semantics, the event loop, `FromExecutor`).

The handles are `Journal`s (`helpers`): a file shows every open and close, also those of worker processes."""

import asyncio
import gc
import pickle
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import pytest
from helpers import (
    CloseFailure,
    Journal,
    OpenFailure,
    Pickling,
    meaning_async,
    outputs_of,
    run_error,
    tokens_lazily,
    tokens_of,
)

import strom as P
from strom import testing
from strom.metrics import StatsRecorder


@pytest.fixture
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "journal.log")


def token_and_item(handle: str, item: int) -> list[tuple[str, int]]:
    return [(handle, item)]


def item_only(handle: str, item: int) -> list[int]:
    """Stateless: the outputs do not depend on the handle (for comparing runs with the reference)."""
    return [item, item + 1]


async def test_one_handle_per_process_on_threads_opened_lazily(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools, name="journal") as handle:
        unused = P.io_stage(P.using(handle, tokens_of))
        assert journal.opens() == []
        outputs = await outputs_of(P.io_stage(P.using(handle, tokens_of), concurrency=8), range(40), pools)
        assert journal.opens() == list(set(outputs))  # one handle for all threads
        assert journal.closes() == []
        del unused
    assert journal.closes() == journal.opens()


async def test_one_handle_per_worker_process(process_pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, process_pools, name="journal") as handle:
        outputs = await outputs_of(P.cpu_stage(P.using(handle, tokens_of), concurrency=4), range(40), process_pools)
        assert sorted(set(outputs)) == sorted(journal.opens())
        assert len(journal.pids()) == len(journal.opens())  # one per process
        assert journal.closes() == []
    assert sorted(journal.closes()) == sorted(journal.opens())  # closed by each process, awaited by the block


async def test_shared_by_stages_and_consecutive_runs(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools) as handle:
        both = P.io_stage(P.using(handle, tokens_of)) | P.cpu_stage(P.using(handle, partial_tokens))
        first = await outputs_of(both, range(5), pools)
        second = await outputs_of(P.io_stage(P.using(handle, tokens_of)), range(5), pools)
    assert len(journal.opens()) == 1  # the io and the cpu threads of this process, both runs
    assert set(first) == set(second) == set(journal.opens())


def partial_tokens(handle: str, token: str) -> list[str]:
    """The handle's token after another stage's: both are the same handle."""
    assert handle == token
    return [handle]


async def test_two_blocks_of_one_opener_are_two_handles(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools) as first, P.worker_handle(journal, pools) as second:
        await outputs_of(P.io_stage(P.using(first, tokens_of)), [1], pools)
        tokens = await outputs_of(P.io_stage(P.using(second, tokens_of)), [1], pools)
        assert len(journal.opens()) == 2
        assert tokens == journal.opens()[1:]
    assert sorted(journal.closes()) == sorted(journal.opens())


async def test_a_use_in_flight_delays_the_close_until_it_ends(pools: P.Pools, journal: Journal) -> None:
    """A suspended `io_stage` generator holds a use: the close waits until the run closes it."""
    async with P.worker_handle(journal, pools) as handle:
        async with P.stream(P.io_stage(P.using(handle, tokens_lazily)), [1_000], pools) as outputs:
            async for _ in outputs:
                break  # the generator stays suspended in its pool thread until the run closes it
    assert journal.closes() == journal.opens()


async def test_a_list_takes_one_pool_task_with_a_handle_too(pools: P.Pools, journal: Journal) -> None:
    """`using` keeps what fn returned: a list comes whole (its use over when fn returns), an iterator is
    streamed within its use (a pool task per item and one for its end)."""
    async with P.worker_handle(journal, pools) as handle:
        for fn, num_pool_tasks in ((tokens_of, 2), (tokens_lazily, (3 + 1) + (2 + 1))):
            recorder = StatsRecorder()
            outputs = await outputs_of(P.io_stage(P.using(handle, fn)), [3, 2], pools, recorder=recorder)
            assert set(outputs) == set(journal.opens())
            assert recorder.stats().step(fn.__name__).num_pool_tasks == num_pool_tasks


async def test_an_iterator_dropped_before_its_first_item_ends_its_use(pools: P.Pools, journal: Journal) -> None:
    """On the event loop a handle opens per input, when the function is called; the iterator it returns holds
    the use, also when nobody ever iterates it."""
    async with P.worker_handle(journal, pools) as handle:
        items = P.using(handle, tokens_lazily)(3)
        assert len(journal.opens()) == 1 and journal.closes() == []
        del items
        gc.collect()  # the free-threaded build may defer what reference counting frees at once
        assert journal.closes() == journal.opens()
        assert P.using(handle, tokens_of)(3) == journal.opens()[1:]  # a list: its use is over
        assert journal.closes() == journal.opens()


async def test_closed_at_the_end_of_a_cancelled_block(pools: P.Pools, journal: Journal) -> None:
    entered = asyncio.Event()

    async def block() -> None:
        async with P.worker_handle(journal, pools) as handle:
            await outputs_of(P.io_stage(P.using(handle, tokens_of)), [1], pools)
            entered.set()
            await asyncio.Event().wait()  # until cancelled

    task = asyncio.create_task(block())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(100):  # the close goes on, shielded, in a helper thread
        if journal.closes():
            break
        await asyncio.sleep(0.01)  # intentional: polls for the background close
    assert journal.closes() == journal.opens()


async def test_errors_of_the_closes_are_raised_as_one_group(process_pools: P.Pools, tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.log", failing_close=True)
    with pytest.RaisesGroup(CloseFailure, CloseFailure, CloseFailure, match="^closing worker handle 'j' failed$"):
        async with P.worker_handle(journal, process_pools, name="j") as handle:
            await outputs_of(P.io_stage(P.using(handle, tokens_of)), [1], process_pools)  # this process
            # both worker processes: two inputs held until both workers took one
            await outputs_of(P.cpu_stage(P.using(handle, slow_tokens), concurrency=2), [1, 2], process_pools)
            assert len(journal.pids()) == 3
    assert len(journal.closes()) == 3


def slow_tokens(handle: str, item: int) -> list[str]:
    time.sleep(0.2)  # intentional: two concurrent inputs spread over both worker processes
    return [handle]


async def test_the_bodys_error_is_chained_to_the_close_errors(pools: P.Pools, tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.log", failing_close=True)
    with pytest.RaisesGroup(CloseFailure) as info:
        async with P.worker_handle(journal, pools) as handle:
            await outputs_of(P.io_stage(P.using(handle, tokens_of)), [1], pools)
            raise KeyError("body")
    assert isinstance(info.value.__context__, KeyError)


async def test_a_use_after_the_block_fails_the_run(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools, name="journal") as handle:
        pass
    with run_error(RuntimeError, "^worker handle 'journal' is closed\nin stage 'tokens_of'$"):
        await outputs_of(P.io_stage(P.using(handle, tokens_of)), [1], pools)
    with pytest.raises(RuntimeError, match="closed"):
        pickle.dumps(handle)  # no process pool task takes it
    assert journal.opens() == []


async def test_a_handle_needs_open_pools(journal: Journal) -> None:
    async with P.Pools.open(cpu_workers=1, io_workers=1) as pools:
        pass
    with pytest.raises(RuntimeError, match="Pools is closed"):
        P.worker_handle(journal, pools)


async def test_per_input_in_the_reference_on_the_event_loop_and_from_an_executor(journal: Journal) -> None:
    async with (
        P.Pools.open_on(cpu=P.FromExecutor(factory=partial(ThreadPoolExecutor, 2)), io=P.Threads(workers=1)) as pools,
        P.worker_handle(journal, pools) as handle,
    ):
        reference = await meaning_async(P.io_stage(P.using(handle, tokens_of)), range(3))
        on_loop = await outputs_of(P.stage(P.using(handle, tokens_of)), range(3), pools)
        on_executor = await outputs_of(P.cpu_stage(P.using(handle, tokens_of)), range(3), pools)
        assert len(set(reference + on_loop + on_executor)) == 9  # a handle per input
        assert sorted(journal.closes()) == sorted(journal.opens())  # each closed with its input


async def test_a_failing_opener_fails_its_input_and_is_retried(pools: P.Pools, tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.log", failing_opens=1)
    async with P.worker_handle(journal, pools, name="journal") as handle:
        stage = P.io_stage(P.using(handle, tokens_of))
        with run_error(OpenFailure, r"cannot open\nopening its handle \(journal\)\nin stage 'tokens_of'"):
            await outputs_of(stage, [1], pools)
        assert await outputs_of(stage, [1], pools) == journal.opens()


def inverse(handle: str, item: int) -> list[int]:
    return [1 // item]


async def test_an_error_of_fn_keeps_the_handle(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools) as handle:
        with run_error(ZeroDivisionError):
            await outputs_of(P.io_stage(P.using(handle, inverse)), [0], pools)
        await outputs_of(P.io_stage(P.using(handle, tokens_of)), [1], pools)
        assert len(journal.opens()) == 1


async def test_lifted_and_in_a_product_branch(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools) as handle:
        lifted: P.Stage[tuple[int, str], tuple[str, str]] = P.first(P.io_stage(P.using(handle, tokens_of)))
        branches: P.Stage[tuple[int, int], tuple[str, tuple[str, int]]] = P.product(
            P.io_stage(P.using(handle, tokens_of)), P.cpu_stage(P.using(handle, token_and_item))
        )
        outputs = await outputs_of(lifted, [(1, "x")], pools) + await outputs_of(branches, [(1, 2)], pools)
    (token,) = journal.opens()
    assert outputs == [(token, "x"), (token, (token, 2))]


def test_on_a_backend_without_shared_memory(journal: Journal) -> None:
    """`PicklingBackend` pickles the handle to its workers, which share this process's table by its key."""
    cpu, io = Pickling(), Pickling()

    async def run() -> list[str]:
        async with P.Pools.open_on(cpu=cpu, io=io) as pools, P.worker_handle(journal, pools) as handle:
            stage = P.io_stage(P.using(handle, tokens_of), concurrency=4) | P.cpu_stage(P.using(handle, partial_tokens))
            return await outputs_of(stage, range(10), pools)

    outputs = asyncio.run(run())
    assert set(outputs) == set(journal.opens())
    assert len(journal.opens()) == 1
    assert journal.closes() == journal.opens()
    assert cpu.num_registered() == io.num_registered() == 0


@pytest.mark.parametrize("cpu_backend", ["thread", "process"])
@pytest.mark.parametrize("name", ["io", "cpu", "chain", "product"])
async def test_a_run_agrees_with_the_reference(journal: Journal, name: str, cpu_backend: P.CpuBackendKind) -> None:
    """A stateless handle: a run's outputs, one handle per process, are the reference's, one per input."""
    async with (
        P.Pools.open(cpu_workers=2, io_workers=4, cpu_backend=cpu_backend) as pools,
        P.worker_handle(journal, pools) as handle,
    ):
        io = P.io_stage(P.using(handle, item_only), concurrency=3)
        cpu = P.cpu_stage(P.using(handle, item_only), concurrency=2)
        pairs: P.Stage[int, tuple[int, int]] = P.duplicate()
        stages: dict[str, P.Stage[int, object]] = {
            "io": io,
            "cpu": cpu,
            "chain": io | cpu,
            "product": pairs | P.product(io, cpu),
        }
        await testing.check_against_reference(stages[name], range(8), pools)


async def test_using_names_the_function_and_the_handle(pools: P.Pools, journal: Journal) -> None:
    async with P.worker_handle(journal, pools, name="journal") as handle:
        assert repr(P.io_stage(P.using(handle, tokens_of))) == "<Stage 'tokens_of' (tokens_of: io, using journal)>"
        assert repr(handle) == "<WorkerHandle 'journal'>"
    assert repr(handle) == "<WorkerHandle 'journal' (closed)>"


async def test_the_default_name_is_the_openers(pools: P.Pools, tmp_path: Path) -> None:
    async with (
        P.worker_handle(opened_file, pools) as named,
        P.worker_handle(partial(opened_file), pools) as nameless,
    ):
        assert (named.name, nameless.name) == ("opened_file", "handle")


@contextmanager
def opened_file() -> Generator[int]:
    raise NotImplementedError  # never opened: only its name counts
    yield 0
