"""Tests of the package as users see it: the public interface."""

import pytest

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
            "Using",
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
