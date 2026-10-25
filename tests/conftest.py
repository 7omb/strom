"""Fixtures shared by the test modules, and the Hypothesis profiles.

Layout: one test module per library module, in the sub-package's directory without its `_`
(`tests/stages/test_factories.py` tests `strom._stages.factories`). A test sits with the module whose
behaviour it checks, also when it runs a whole pipeline. Two modules map to no library module:
`test_init.py` (the public interface) and `test_typing.py` (static typing). Shared helpers are in
`helpers.py`, the generated pipelines in `strategies.py`; each test module creates its own test data.
The examples are not part of the tests: `bin/run_examples.py` runs them.

Requires pytest, pytest-asyncio and hypothesis. `async def` tests and fixtures run on an event loop of
their own per test (pytest-asyncio, `asyncio_mode = "auto"` in `pyproject.toml`). The static typing tests
run mypy in a subprocess and are skipped if mypy is not installed. Functions used with the process pool are
defined at module level so that they can be pickled.

Hypothesis profiles: `dev` by default, `ci` with `pytest --hypothesis-profile=ci` (pytest loads this
file before the Hypothesis plugin applies that option, which a test module's own profile would override)."""

from collections.abc import AsyncIterator, Iterator

import helpers
import pytest
from hypothesis import HealthCheck, settings

import strom as P
from strom._runtime import iterator_registry
from strom._runtime.worker_handles import process_handles

settings.register_profile("dev", deadline=None, max_examples=60, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("ci", settings.get_profile("dev"), max_examples=300)
settings.load_profile("dev")


@pytest.fixture(autouse=True)
def _reset_tracker() -> None:
    helpers.TRACK = helpers.Tracker()


@pytest.fixture(autouse=True)
def _no_iterator_left_registered() -> Iterator[None]:
    """Every iterator a test registers in this process's registry (the one of threads without a registry of
    their own) is unregistered by its end: a registry holds its iterators strongly, so a missed release would
    leak (`strom._runtime.iterator_registry`). The pool threads of `Threads` have registries of their own
    and check them at their end: a missed release fails the close of the pools."""
    yield
    left = dict(iterator_registry._PROCESS_REGISTRY.iterators)
    iterator_registry._PROCESS_REGISTRY.iterators.clear()  # the next test starts empty, also after a failure here
    assert left == {}


@pytest.fixture(autouse=True)
def _no_handle_left_open() -> Iterator[None]:
    """Every worker handle a test opens in this process is closed by its end (its block closes it)."""
    yield
    held = process_handles._process_table.current.held()
    for key in held:
        process_handles.close_process_handle(key)
    assert held == []


@pytest.fixture
async def pools() -> AsyncIterator[P.Pools]:
    async with P.Pools.open(cpu_workers=2, io_workers=8, cpu_backend="thread") as pools:
        yield pools


@pytest.fixture
async def process_pools() -> AsyncIterator[P.Pools]:
    async with P.Pools.open(cpu_workers=2, io_workers=4, cpu_backend="process") as pools:
        yield pools
