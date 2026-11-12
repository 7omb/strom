"""Tests of `strom._runtime.worker_handles.handle_table`: a `HandleTable` (each test its own), its keys' states,
uses in flight, opens and closes."""

import threading
import time
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from helpers import SATURATION_GRACE_TIME, WAIT_LIMIT_TIME, CloseFailure, Failure, Journal, OpenFailure

from strom._runtime.worker_handles.handle_table import HandleTable


def test_concurrent_first_uses_open_the_handle_once(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log", open_time=0.05)
    num_threads = 8
    start = threading.Barrier(num_threads)

    def use() -> str:
        start.wait(WAIT_LIMIT_TIME)
        with table.use("key", "journal", journal) as token:
            return token

    with ThreadPoolExecutor(num_threads) as executor:
        tokens = list(executor.map(lambda _: use(), range(num_threads)))
    assert len(journal.opens()) == 1
    assert set(tokens) == set(journal.opens())
    table.close("key")
    assert journal.closes() == journal.opens()


def test_a_close_waits_for_a_suspended_use(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log")

    def suspended() -> Generator[str]:
        with table.use("key", "journal", journal) as token:
            yield token
            yield token

    generator = suspended()
    assert next(generator) in journal.opens()
    closing = threading.Thread(target=table.close, args=("key",))
    closing.start()
    closing.join(SATURATION_GRACE_TIME)
    assert closing.is_alive()  # waits for the generator, which still uses the handle
    assert journal.closes() == []
    generator.close()
    closing.join(WAIT_LIMIT_TIME)
    assert not closing.is_alive()
    assert journal.closes() == journal.opens()


def test_a_use_after_the_close_is_refused(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log")
    with table.use("key", "journal", journal):
        pass
    table.close("key")
    with (
        pytest.raises(RuntimeError, match=r"^worker handle 'journal' is closed$"),
        table.use("key", "journal", journal),
    ):
        pass
    table.close("never used")  # marks it closed too
    with pytest.raises(RuntimeError, match="closed"), table.use("never used", "journal", journal):
        pass
    assert len(journal.opens()) == 1


def test_a_use_after_the_mark_is_refused_and_one_in_flight_goes_on(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log")
    with table.use("key", "journal", journal) as token:
        table.mark_closed("key")
        with pytest.raises(RuntimeError, match="closed"), table.use("key", "journal", journal):
            pass
        assert journal.opens() == [token]
    assert journal.closes() == []  # marked, not closed
    table.close("key")
    assert journal.closes() == journal.opens()


def test_an_open_in_flight_at_the_mark_is_closed_by_the_close(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log", open_time=0.2)

    def use() -> str:
        with table.use("key", "journal", journal) as token:
            return token

    with ThreadPoolExecutor(1) as executor:
        token = executor.submit(use)
        time.sleep(0.1)  # intentional: the open has begun (it takes 0.2 s)
        table.mark_closed("key")
        assert token.result(WAIT_LIMIT_TIME) in journal.opens()  # admitted before the mark: goes on
    with pytest.raises(RuntimeError, match="closed"), table.use("key", "journal", journal):  # the mark stays
        pass
    assert table.held() == ["key"]
    table.close("key")
    assert journal.closes() == journal.opens()
    assert table.held() == []


def test_a_failing_opener_is_noted_and_retried(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log", failing_opens=1)
    with pytest.raises(OpenFailure) as info, table.use("key", "journal", journal):
        pass
    assert info.value.__notes__ == ["opening its handle (journal)"]
    assert table.held() == []
    with table.use("key", "journal", journal) as token:  # nothing was kept: this use opens again
        assert journal.opens() == [token]
    table.close("key")


def test_an_error_of_a_use_keeps_the_handle(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log")
    with pytest.raises(Failure), table.use("key", "journal", journal):
        raise Failure
    with table.use("key", "journal", journal):
        pass
    assert len(journal.opens()) == 1
    assert journal.closes() == []
    table.close("key")


def test_held_handles_are_in_the_order_of_opening_not_of_first_use(tmp_path: Path) -> None:
    table = HandleTable()
    late = Journal(tmp_path / "late.log", failing_opens=1)  # used first, opened second
    with pytest.raises(OpenFailure), table.use("late", "journal", late):
        pass
    with table.use("early", "journal", Journal(tmp_path / "early.log")):
        pass
    with table.use("late", "journal", late):
        pass
    assert table.held() == ["late", "early"]  # newest first
    table.close_all()


def test_a_close_raises_the_error_of_the_handles_exit_and_closes_once(tmp_path: Path) -> None:
    table = HandleTable()
    journal = Journal(tmp_path / "journal.log", failing_close=True)
    with table.use("key", "journal", journal):
        pass
    with pytest.raises(CloseFailure):
        table.close("key")
    table.close("key")  # closed already: nothing more to close or to raise
    assert len(journal.closes()) == 1
    assert table.held() == []
