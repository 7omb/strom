"""Tests of `strom._metrics.stats`: statistics, combined recorders and `diagnose`."""

import dataclasses

import pytest
from helpers import bag, boom, collect, dup, inc, meaning, neg, outputs_of, run_error, sleep_10ms, stats_of
from hypothesis import given, settings
from strategies import NONEMPTY_INPUTS, stages

import strom as P
from strom._metrics.stats import _StepTotals
from strom.metrics import (
    Event,
    InputHandled,
    PoolTaskFinished,
    Recorder,
    RunFinished,
    RunStarted,
    RunStats,
    StatsRecorder,
    StepId,
    StepStats,
    TaskFinished,
    combine_recorders,
    diagnose,
)


def same(item: int) -> list[int]:
    return [item]


def test_statistics_count_items_and_split_time() -> None:
    outputs, stats = stats_of(P.io_stage(sleep_10ms, concurrency=4) | P.stage(dup) | P.stage(neg), range(20))
    assert len(outputs) == 40
    sleep, group = stats.step("sleep_10ms"), stats.step("dup | neg")
    assert [str(s.step_id) for s in stats.step_stats] == ["1:sleep_10ms", "2:dup | neg"]  # fused
    assert (
        sleep.num_items_in,
        sleep.num_items_out,
        sleep.step_id.concurrency,
    ) == (20, 20, 4)
    assert (group.num_items_in, group.num_items_out) == (20, 40)
    # per input one pool task of io_stage: `sleep_10ms` returns a list, which comes whole
    assert sleep.num_pool_tasks == 20
    assert sleep.pool_running_time >= 20 * 0.01 * 0.9
    # sleeping takes no CPU: measured with the default cpu_clock (the pool thread's CPU time)
    assert sleep.pool_cpu_time < sleep.pool_running_time / 2
    assert all(
        s.num_errors == 0 and min(s.busy_time, s.idle_time, s.blocked_time, s.pool_wait_time) >= 0
        for s in stats.step_stats
    )
    assert stats.wall_time > 0
    assert stats.outcome == "done"
    assert all(0 <= s.utilization <= 1.05 for s in stats.step_stats)


def test_statistics_from_events() -> None:
    recorder = StatsRecorder()
    step_id = StepId((), 1, "s", 2)
    never_started = StepId((), 2, "t", 1)
    events: list[Event] = [
        RunStarted(started_at=0.0, steps=(step_id, never_started)),
        InputHandled(
            step_id=step_id,
            task=0,
            wait_started_at=0.0,
            started_at=1.0,
            ended_at=5.0,
            num_items_out=3,
            blocked_time=1.0,
            outcome="done",
        ),
        PoolTaskFinished(step_id=step_id, submitted_at=1.0, ended_at=4.0, running_time=2.0, cpu_time=0.5),
        InputHandled(
            step_id=step_id,
            task=0,
            wait_started_at=5.0,
            started_at=6.0,
            ended_at=7.0,
            num_items_out=1,
            blocked_time=0.0,
            outcome="failed",
        ),
        TaskFinished(step_id=step_id, task=0, wait_started_at=7.0, ended_at=7.0),
        InputHandled(
            step_id=step_id,
            task=1,
            wait_started_at=0.0,
            started_at=2.0,
            ended_at=8.0,
            num_items_out=0,
            blocked_time=0.5,
            outcome="cancelled",
        ),
        TaskFinished(step_id=step_id, task=1, wait_started_at=8.0, ended_at=8.0),
        RunFinished(ended_at=10.0, outcome="failed"),
    ]
    for event in events:
        recorder(event)
    stats = recorder.stats()
    s, t = stats.step_stats
    assert (stats.wall_time, stats.outcome) == (10.0, "failed")
    assert (
        s.num_items_in,
        s.num_items_out,
        s.busy_time,
        s.idle_time,
        s.blocked_time,
        s.num_errors,
        s.num_cancelled,
    ) == (3, 4, 9.5, 4.0, 1.5, 1, 1)
    assert (s.num_pool_tasks, s.pool_wait_time, s.pool_running_time, s.pool_cpu_time) == (1, 1.0, 2.0, 0.5)
    assert s.utilization == 9.5 / (2 * 10.0)
    assert t == StepStats(
        step_id=never_started,
        num_items_in=0,
        num_items_out=0,
        busy_time=0.0,
        idle_time=0.0,
        blocked_time=0.0,
        num_errors=0,
        num_cancelled=0,
        num_pool_tasks=0,
        pool_wait_time=0.0,
        pool_running_time=0.0,
        pool_cpu_time=0.0,
        utilization=0.0,
    )  # shown with zeros
    assert str(stats).startswith("run: 10.000 s, failed\n")


def test_the_running_totals_hold_every_statistic() -> None:
    # `_StepTotals.frozen` names each field: a statistic added to one class only would go unnoticed
    totals = [f.name for f in dataclasses.fields(_StepTotals)]
    assert totals == [f.name for f in dataclasses.fields(StepStats) if f.name != "utilization"]


async def test_a_statistics_recorder_records_one_run(pools: P.Pools) -> None:
    recorder = StatsRecorder()
    async with P.stream(P.io_stage(inc), range(10), pools, recorder=recorder) as outputs:
        with pytest.raises(RuntimeError, match="has not finished"):
            recorder.stats()
        assert len([out async for out in outputs]) == 10
    with run_error(RuntimeError, "records one run"):  # the second run fails at its start
        await outputs_of(P.stage(neg), range(3), pools, recorder=recorder)
    assert [(s.step_id.name, s.num_items_in) for s in recorder.stats().step_stats] == [("inc", 10)]


async def test_a_run_overlapping_another_on_one_statistics_recorder_fails_at_its_start(pools: P.Pools) -> None:
    recorder = StatsRecorder()
    async with P.stream(P.io_stage(inc), range(10), pools, recorder=recorder) as outputs:
        with run_error(RuntimeError, "records one run"):
            await outputs_of(P.stage(neg), range(3), pools, recorder=recorder)
        assert len([out async for out in outputs]) == 10  # the first run goes on
    assert [(s.step_id.name, s.num_items_in) for s in recorder.stats().step_stats] == [("inc", 10)]


def test_failures_are_counted() -> None:
    recorder = StatsRecorder()
    with run_error(ValueError, "^boom"):
        collect(P.io_stage(boom), range(10), recorder=recorder)
    stats = recorder.stats()
    assert {s.step_id.name: s.num_errors for s in stats.step_stats} == {"boom": 1}
    assert (stats.wall_time > 0, stats.outcome) == (True, "failed")  # the end of a failed run is recorded too


def test_combined_recorders_receive_every_event() -> None:
    first, second = StatsRecorder(), StatsRecorder()
    collect(P.io_stage(inc), range(20), recorder=combine_recorders(first, second))
    counts = [
        [(s.step_id.name, s.num_items_in, s.num_items_out) for s in r.stats().step_stats] for r in (first, second)
    ]
    assert counts[0] == counts[1] == [("inc", 20, 20)]


class RecorderFailure(Exception):
    pass


def failing_on[E: Event](kind: type[E], received: list[Event]) -> Recorder:
    """A recorder appending each event to `received`, failing on events of `kind`."""

    def record(event: Event) -> None:
        received.append(event)
        if isinstance(event, kind):
            raise RecorderFailure(type(event).__name__)

    return record


def test_combined_recorders_that_started_get_the_end_of_the_run() -> None:
    first: list[Event] = []
    second: list[Event] = []
    third: list[Event] = []
    record = combine_recorders(first.append, failing_on(RunStarted, second), third.append)
    with pytest.raises(RecorderFailure):
        record(RunStarted(started_at=1.0, steps=()))
    assert [(type(e).__name__, getattr(e, "outcome", None)) for e in first] == [
        ("RunStarted", None),
        ("RunFinished", "failed"),
    ]
    (finished,) = first[1:]
    assert isinstance(finished, RunFinished)
    assert finished.ended_at == 1.0
    assert [type(e).__name__ for e in second] == ["RunStarted"]  # it raised: no RunFinished
    assert third == []


def test_the_end_of_a_run_reaches_every_combined_recorder() -> None:
    received: list[list[Event]] = [[], [], []]
    finished = RunFinished(ended_at=2.0, outcome="done")
    one_failing = combine_recorders(failing_on(RunFinished, received[0]), received[1].append)
    with pytest.raises(RecorderFailure):
        one_failing(finished)
    assert received[1] == [finished]
    two_failing = combine_recorders(
        failing_on(RunFinished, received[0]), received[1].append, failing_on(RunFinished, received[2])
    )
    with pytest.RaisesGroup(RecorderFailure, RecorderFailure):
        two_failing(finished)
    assert received[1] == [finished, finished]  # once per combined recorder
    assert received[2] == [finished]


def test_a_combined_recorder_failing_after_one_that_started_fails_the_run_at_its_start() -> None:
    first: list[Event] = []
    second: list[Event] = []
    with run_error(RecorderFailure):
        collect(P.io_stage(inc), range(5), recorder=combine_recorders(first.append, failing_on(RunStarted, second)))
    assert [type(e).__name__ for e in first] == ["RunStarted", "RunFinished"]
    assert [type(e).__name__ for e in second] == ["RunStarted"]


def test_steps_inside_product_are_measured() -> None:
    _, stats = stats_of(P.product(P.io_stage(inc), P.stage(neg)), [(i, i) for i in range(10)])
    assert sorted((s.step_id.name, s.num_items_in) for s in stats.step_stats) == [("inc", 10), ("neg", 10)]


def test_diagnose_names_the_step_that_limits_throughput() -> None:
    _, stats = stats_of(P.io_stage(sleep_10ms, concurrency=2) | P.stage(neg), range(16))
    assert [h.step_id.name for h in diagnose(stats)] == ["sleep_10ms"]


def test_diagnose_names_a_saturated_pool() -> None:
    # 8 in flight, 1 thread
    _, stats = stats_of(P.io_stage(sleep_10ms, concurrency=8), range(16), io_workers=1)
    hints = diagnose(stats)
    assert [h.step_id.name for h in hints] == ["sleep_10ms"]
    assert "saturated" in hints[0].message


def test_diagnose_is_a_pure_function_of_the_statistics() -> None:
    def stats(
        busy_time: float, pool_wait_time: float, pool_running_time: float = 1.0, wall_time: float = 10.0
    ) -> RunStats:
        step_stats = StepStats(
            step_id=StepId((), 1, "s", 1),
            num_items_in=5,
            num_items_out=5,
            busy_time=busy_time,
            idle_time=0.0,
            blocked_time=0.0,
            num_errors=0,
            num_cancelled=0,
            num_pool_tasks=5,
            pool_wait_time=pool_wait_time,
            pool_running_time=pool_running_time,
            pool_cpu_time=0.0,
            utilization=busy_time / wall_time if wall_time > 0 else 0.0,
        )
        return RunStats(wall_time, (step_stats,), "done")

    assert diagnose(stats(busy_time=2.0, pool_wait_time=0.0)) == []
    assert "limits throughput" in diagnose(stats(busy_time=9.0, pool_wait_time=0.0))[0].message
    assert "saturated" in diagnose(stats(busy_time=2.0, pool_wait_time=4.0))[0].message
    # the thresholds themselves give no hint: utilization 0.7, a pool wait share of 0.3
    assert diagnose(stats(busy_time=7.0, pool_wait_time=0.0)) == []
    assert "limits throughput" in diagnose(stats(busy_time=7.1, pool_wait_time=0.0))[0].message
    assert diagnose(stats(busy_time=2.0, pool_wait_time=3.0, pool_running_time=7.0)) == []
    assert "saturated" in diagnose(stats(busy_time=2.0, pool_wait_time=3.1, pool_running_time=6.9))[0].message
    # without wall time (nothing measured) no utilization
    no_wall_time = stats(busy_time=9.0, pool_wait_time=0.0, wall_time=0.0)
    assert no_wall_time.step_stats[0].utilization == 0.0
    assert diagnose(no_wall_time) == []


def test_pool_wait_time_is_never_negative() -> None:
    # The running time comes from the pool worker's clock readings, the pool task's interval from the event
    # loop's: the running time can exceed the interval.
    recorder = StatsRecorder()
    step_id = StepId((), 1, "s", 1)
    events: list[Event] = [
        RunStarted(started_at=0.0, steps=(step_id,)),
        PoolTaskFinished(step_id=step_id, submitted_at=1.0, ended_at=2.0, running_time=1.5, cpu_time=0.0),
        RunFinished(ended_at=3.0, outcome="done"),
    ]
    for event in events:
        recorder(event)
    (s,) = recorder.stats().step_stats
    assert (s.pool_wait_time, s.pool_running_time) == (0.0, 1.5)


@settings(max_examples=30)
@given(stages(), NONEMPTY_INPUTS)
def test_recording_does_not_change_results(stage: P.Stage[int, int], items: list[int]) -> None:
    counted = P.io_stage(same, name="counted") | stage  # never fused with the stage: its count stays visible
    outputs, stats = stats_of(counted, items)
    assert bag(outputs) == bag(meaning(counted, items))
    assert (stats.step_stats[0].step_id.name, stats.step_stats[0].num_items_in) == ("counted", len(items))
    assert all(min(s.busy_time, s.idle_time, s.blocked_time, s.pool_wait_time) >= 0 for s in stats.step_stats)


def test_statistics_of_a_step_by_name() -> None:
    _, stats = stats_of(P.io_stage(inc) | P.stage(dup) | P.stage(neg), range(5))
    assert stats.step("dup | neg").num_items_out == 10  # a group: its chain
    with pytest.raises(KeyError):
        stats.step("missing")
    once = P.io_stage(inc)
    _, twice = stats_of(once | once, range(5))  # one step object, two occurrences
    with pytest.raises(ValueError, match="2 step occurrences"):
        twice.step("inc")
