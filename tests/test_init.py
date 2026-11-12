"""Tests of the package as users see it: the public interface, and the example of `README.md`."""

import subprocess
import sys
from pathlib import Path

import pytest
from helpers import readme_example

import strom as P
from strom import backends, metrics


def test_api_requires_explicit_values() -> None:
    same: P.Stage[int, int] = P.identity()
    # each checker rejects these calls, and each has an ignore comment of its own (`.claude/rules/typing.md`)
    with pytest.raises(TypeError):
        P.PoolConfig()  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        P.stream(same, [1])  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[missing-argument]
    with pytest.raises(TypeError):
        P.flatten(concurrency=2)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]  # ty: ignore[unknown-argument]
    with pytest.raises(TypeError, match="abstract"):
        P.Stage(name="x")


def test_public_interface() -> None:
    assert sorted(P.__all__) == sorted(
        [
            "Stage",
            "CpuBackendKind",
            "PoolConfig",
            "Pools",
            "Threads",
            "Processes",
            "FromExecutor",
            "default_cpu_workers",
            "default_io_workers",
            "worker_handle",
            "WorkerHandle",
            "using",
            "stage",
            "async_stage",
            "io_stage",
            "cpu_stage",
            "where",
            "flatten",
            "identity",
            "swap",
            "fst",
            "snd",
            "untag",
            "duplicate",
            "first",
            "second",
            "product",
            "Left",
            "Right",
            "route",
            "left",
            "right",
            "tag_by",
            "gather",
            "loop",
            "stream",
            "RunFailed",
        ]
    )


def test_public_interface_of_the_metrics() -> None:
    expected = [
        "Recorder",
        "StatsRecorder",
        "combine_recorders",
        "RunStats",
        "StepStats",
        "diagnose",
        "Hint",
        "Event",
        "RunStarted",
        "InputHandled",
        "TaskFinished",
        "PoolTaskFinished",
        "RunFinished",
        "Outcome",
        "StepId",
        "Enclosing",
        "Part",
    ]
    assert sorted(metrics.__all__) == sorted(expected)
    assert {name for name in vars(metrics) if not name.startswith("_")} == set(expected)  # nothing else shows
    assert not set(expected) & set(vars(P))  # one import path per name: none also at the top level


def test_public_interface_for_backend_implementers() -> None:
    assert sorted(backends.__all__) == sorted(
        [
            "Backend",
            "StreamingBackend",
            "WorkerId",
            "init_worker",
            "release_scope",
            "init_handles",
            "close_process_handle",
            "close_all_process_handles",
        ]
    )


def test_the_readme_example_runs(tmp_path: Path) -> None:
    """As a script of its own: its `cpu_stage` runs in worker processes, which import its `__main__`."""
    done = subprocess.run(
        [sys.executable, readme_example(tmp_path)], cwd=tmp_path, capture_output=True, text=True, timeout=60
    )
    assert done.returncode == 0, done.stderr
    *values, total = done.stdout.splitlines()
    assert len(values) == 20, "one per input"
    assert total == f"total: {sum(map(int, values))}"
