"""Tests of `strom._runtime.worker_handles.process_handles`: the worker handles of this process, shared by marked
threads, per input in unmarked ones, closed by the closes a backend runs in each of its processes."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from helpers import CloseFailure, Journal

from strom._runtime.worker_handles import process_handles


def test_marked_threads_share_the_handle_unmarked_ones_open_it_per_use(tmp_path: Path) -> None:
    journal = Journal(tmp_path / "journal.log")

    def token() -> str:
        with process_handles.use_handle("key", "journal", journal) as opened:
            return opened

    with ThreadPoolExecutor(1, initializer=process_handles.init_handles) as marked, ThreadPoolExecutor(1) as unmarked:
        shared = {marked.submit(token).result() for _ in range(2)}
        per_use = {unmarked.submit(token).result() for _ in range(2)}
    assert len(shared) == 1
    assert len(per_use) == 2
    assert set(journal.closes()) == per_use  # each closed after its use
    process_handles.close_process_handle("key")
    assert set(journal.closes()) == per_use | shared


def test_close_all_process_handles_closes_newest_first_and_raises_every_error(tmp_path: Path) -> None:
    journals = [Journal(tmp_path / f"{num}.log", failing_close=num != 1) for num in range(3)]
    table = process_handles._process_table.current
    for num, journal in enumerate(journals):
        with table.use(f"key {num}", "journal", journal):
            pass
    assert table.held() == ["key 2", "key 1", "key 0"]
    with pytest.RaisesGroup(CloseFailure, CloseFailure, match="^closing the worker handles failed$"):
        process_handles.close_all_process_handles()
    assert all(len(journal.closes()) == 1 for journal in journals)
    assert table.held() == []


@pytest.mark.filterwarnings("ignore:This process .* is multi-threaded:DeprecationWarning")  # the child only writes
def test_a_forked_child_gets_an_empty_table(tmp_path: Path) -> None:
    table = process_handles._process_table.current
    with table.use("forked key", "journal", Journal(tmp_path / "journal.log")):
        pass
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:  # the child reports what its table holds, and leaves without running any cleanup
        os.write(write_fd, b"held" if process_handles._process_table.current.held() else b"empty")
        os._exit(0)
    os.close(write_fd)
    assert os.read(read_fd, 10) == b"empty"
    os.close(read_fd)
    os.waitpid(pid, 0)
    process_handles.close_process_handle("forked key")
