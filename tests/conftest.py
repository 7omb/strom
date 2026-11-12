"""Fixtures shared by the test modules, and the Hypothesis profiles.

Layout: one test module per library module, in the sub-package's directory without its `_`
(`tests/stages/test_factories.py` tests `strom._stages.factories`). A test sits with the module whose
behaviour it checks, also when it runs a whole pipeline. Three modules map to no library module:
`test_init.py` (the public interface), `test_packages.py` (the import order of the packages, read from their
sources with `package_imports.py`) and `test_typing.py` (static typing). Shared helpers are in
`helpers.py`, the generated pipelines in `strategies.py`; each test module creates its own test data.
The examples are not part of the tests: `bin/run_examples.py` runs them.

The development tools (`strom_tools` in `tools/`, which the scripts in `bin/` and the Claude Code hooks run) are
tested in `tests/tools/`, laid out like their package; `tests/tools/test_structure.py` checks the package as a
whole (its imports, its layers, the wrappers). Their helpers are in `tool_helpers.py`, and a test module's base
name is unique in `tests/` (pytest imports it by that name: `test_hook_events.py` beside `test_events.py`).

Requires pytest, pytest-asyncio and hypothesis. `async def` tests and fixtures run on an event loop of
their own per test (pytest-asyncio, `asyncio_mode = "auto"` in `pyproject.toml`). The static typing tests
run mypy in a subprocess and are skipped if mypy is not installed. Functions used with the process pool are
defined at module level so that they can be pickled.

Hypothesis profiles: `dev` by default, `ci` with `pytest --hypothesis-profile=ci` (pytest loads this
file before the Hypothesis plugin applies that option, which a test module's own profile would override).

A hung test: `kill -USR1 PID` of its pytest process (an xdist worker, with `-n`) writes the stack of every
thread of it to `.checks/stacks/PID.txt` (stderr is pytest's capture), and the test goes on; the file goes at
the end of the run if it stayed empty."""

import faulthandler
import os
import signal
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TextIO

import helpers
import pytest
import tool_helpers
from hypothesis import HealthCheck, settings

import strom as P
from strom._runtime import iterator_registry
from strom._runtime.worker_handles import process_handles
from strom_tools.workspace.repository import Repository

settings.register_profile("dev", deadline=None, max_examples=60, suppress_health_check=[HealthCheck.too_slow])
settings.register_profile("ci", settings.get_profile("dev"), max_examples=300)
settings.load_profile("dev")

_STACKS = Path(__file__).resolve().parents[1] / ".checks" / "stacks" / f"{os.getpid()}.txt"


_stacks_files: list[TextIO] = []


def pytest_configure() -> None:
    _STACKS.parent.mkdir(parents=True, exist_ok=True)
    _stacks_files.append(_STACKS.open("w", encoding="utf-8"))
    faulthandler.register(signal.SIGUSR1, file=_stacks_files[-1], all_threads=True)


def pytest_unconfigure() -> None:
    faulthandler.unregister(signal.SIGUSR1)
    for file in _stacks_files:
        file.close()
    if _STACKS.exists() and _STACKS.stat().st_size == 0:
        _STACKS.unlink()


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


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Repository:
    """For the tool tests: an empty git repository with an identity to commit with (the jail has none),
    unaffected by the user's git configuration, by the make that runs the tests (`make test ARGS=...` hands its
    variables down, in the environment, to a make that a tool starts) and by pytest-xdist (a pytest that a tool
    starts in a worker would take itself for one: pytest-benchmark then measures nothing)."""
    xdist = ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID")
    for variable in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "ARGS", "FILES", "RUN", *xdist):
        monkeypatch.delenv(variable, raising=False)
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "A Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.org")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    root = tmp_path / "repository"
    root.mkdir()
    made = Repository(root.resolve())
    tool_helpers.git(made, "init", "--quiet", "--initial-branch=main")
    return made
