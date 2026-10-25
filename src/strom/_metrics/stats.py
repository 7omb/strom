"""Statistics: a recorder folding events into run statistics, and hints from them."""

from dataclasses import dataclass
from typing import Final, assert_never, final, override

from strom._metrics.events import (
    Event,
    InputHandled,
    Outcome,
    PoolTaskFinished,
    Recorder,
    RunFinished,
    RunStarted,
    StepId,
    TaskFinished,
)


@final
@dataclass(frozen=True, slots=True)
class StepStats:
    """Totals of one step occurrence in one run (times in seconds, summed over its tasks).

    Every input a task took counts in `num_items_in`, its time as busy and blocked time; a failed one also
    in `num_errors`, a cancelled one (the run failed elsewhere) in `num_cancelled`. Per task, busy, idle and
    blocked time add up to its lifetime."""

    step_id: StepId
    num_items_in: int
    num_items_out: int
    busy_time: float  # handling inputs, without waiting for downstream
    idle_time: float  # waiting for input
    blocked_time: float  # waiting for downstream (backpressure)
    num_errors: int
    num_cancelled: int
    num_pool_tasks: int
    pool_wait_time: float
    """The time its pool tasks spent outside the user's function: from submitting to the result's arrival,
    less the running time measured in the pool worker. Queueing for a pool worker, and on a backend without
    shared memory also pickling and transport."""
    pool_running_time: float
    pool_cpu_time: float
    utilization: float
    """Share of the step's capacity (concurrency x the run's wall time) spent busy; 0 without wall time."""


@final
@dataclass(frozen=True, slots=True)
class RunStats:
    """The statistics of one run (`StatsRecorder.stats()`): its wall time in seconds, from entering the block
    of `stream` to leaving it, a `StepStats` per step occurrence, in the order of the stage (a step that never
    started shows zeros), and how the run ended.

    `str()` gives a table of them."""

    wall_time: float
    step_stats: tuple[StepStats, ...]
    outcome: Outcome

    def step(self, name: str) -> StepStats:
        """The statistics of the step occurrence named `name` (a group: its chain, e.g. "dup | neg").

        KeyError if no step has that name; ValueError if several occurrences do (use `step_stats`)."""
        found = [s for s in self.step_stats if s.step_id.name == name]
        if not found:
            raise KeyError(name)
        if len(found) > 1:
            raise ValueError(f"{len(found)} step occurrences are named {name!r}: see step_stats")
        return found[0]

    @override
    def __str__(self) -> str:
        width = max([28, *(len(str(s.step_id)) + 1 for s in self.step_stats)])
        header = (
            f"{'step':<{width}}{'conc':>5}{'in':>9}{'out':>9}{'util':>7}{'busy':>9}"
            f"{'idle':>9}{'blocked':>9}{'pool wait':>10}{'pool running':>13}{'pool cpu':>9}"
        )
        rows = [
            f"{s.step_id!s:<{width}}{s.step_id.concurrency:>5}{s.num_items_in:>9}{s.num_items_out:>9}"
            f"{s.utilization:>7.0%}{s.busy_time:>9.3f}{s.idle_time:>9.3f}"
            f"{s.blocked_time:>9.3f}{s.pool_wait_time:>10.3f}{s.pool_running_time:>13.3f}"
            f"{s.pool_cpu_time:>9.3f}"
            for s in self.step_stats
        ]
        return "\n".join([f"run: {self.wall_time:.3f} s, {self.outcome}", header, *rows])


@dataclass
class _StepTotals:
    """The running totals of a `StepStats`: its fields except `utilization`, computed by `frozen`."""

    step_id: StepId
    num_items_in: int = 0
    num_items_out: int = 0
    busy_time: float = 0.0
    idle_time: float = 0.0
    blocked_time: float = 0.0
    num_errors: int = 0
    num_cancelled: int = 0
    num_pool_tasks: int = 0
    pool_wait_time: float = 0.0
    pool_running_time: float = 0.0
    pool_cpu_time: float = 0.0

    def frozen(self, wall_time: float) -> StepStats:
        capacity = self.step_id.concurrency * wall_time
        # keywords: most fields are floats, so a positional mix-up would pass every type checker
        return StepStats(
            step_id=self.step_id,
            num_items_in=self.num_items_in,
            num_items_out=self.num_items_out,
            busy_time=self.busy_time,
            idle_time=self.idle_time,
            blocked_time=self.blocked_time,
            num_errors=self.num_errors,
            num_cancelled=self.num_cancelled,
            num_pool_tasks=self.num_pool_tasks,
            pool_wait_time=self.pool_wait_time,
            pool_running_time=self.pool_running_time,
            pool_cpu_time=self.pool_cpu_time,
            utilization=self.busy_time / capacity if capacity > 0 else 0.0,
        )


_ONE_RUN = "a StatsRecorder records one run: create one per run"


@final
class StatsRecorder:
    """A recorder aggregating the events of ONE run into `stats()`.

    Single-use, like an asyncio TaskGroup: a second run fails at its start (a recorder error), leaving the
    first run's statistics intact. Events arrive on the event-loop thread, so no locking is needed."""

    def __init__(self) -> None:
        self._totals: dict[StepId, _StepTotals] = {}
        self._started_at: float | None = None
        self._stats: RunStats | None = None

    def stats(self) -> RunStats:
        """The statistics of the run, once it has finished (RuntimeError before)."""
        if self._stats is None:
            raise RuntimeError("the run has not finished: its statistics are complete at its end")
        return self._stats

    def __call__(self, event: Event) -> None:
        match event:  # class patterns without captures: capturing positionally costs more per event
            case InputHandled():  # the most frequent first
                totals = self._totals[event.step_id]
                totals.num_items_in += 1
                totals.num_items_out += event.num_items_out
                totals.idle_time += event.started_at - event.wait_started_at
                totals.busy_time += event.ended_at - event.started_at - event.blocked_time
                totals.blocked_time += event.blocked_time
                if event.outcome != "done":
                    if event.outcome == "failed":
                        totals.num_errors += 1
                    else:
                        totals.num_cancelled += 1
            case PoolTaskFinished():
                totals = self._totals[event.step_id]
                totals.num_pool_tasks += 1
                pool_time = event.ended_at - event.submitted_at
                totals.pool_wait_time += max(0.0, pool_time - event.running_time)
                totals.pool_running_time += event.running_time
                totals.pool_cpu_time += event.cpu_time
            case TaskFinished():
                self._totals[event.step_id].idle_time += event.ended_at - event.wait_started_at
            case RunStarted():
                if self._started_at is not None:
                    raise RuntimeError(_ONE_RUN)
                self._started_at = event.started_at
                self._totals = {step_id: _StepTotals(step_id) for step_id in event.steps}
            case RunFinished():
                if self._started_at is None:
                    raise RuntimeError("RunFinished without RunStarted")
                wall_time = event.ended_at - self._started_at
                step_stats = tuple(totals.frozen(wall_time) for totals in self._totals.values())
                self._stats = RunStats(wall_time, step_stats, event.outcome)
            case _:
                assert_never(event)


def combine_recorders(recorder: Recorder, /, *other_recorders: Recorder) -> Recorder:
    """A recorder passing every event to all given recorders, e.g. statistics and an exporter.

    Like `contextlib.ExitStack`, every recorder whose `RunStarted` call returned gets the `RunFinished`, also
    if another one raises: if one raises on `RunStarted`, those before it get a `RunFinished` (outcome
    "failed") at once; `RunFinished` reaches every recorder. Their errors are raised after the last one
    (several as an ExceptionGroup)."""
    recorders = (recorder, *other_recorders)

    def record(event: Event) -> None:
        match event:
            case RunStarted():
                _start_all(recorders, event)
            case RunFinished():
                _raise_all(_finish_all(recorders, event))
            case _:
                for each in recorders:
                    each(event)

    return record


def _start_all(recorders: tuple[Recorder, ...], event: RunStarted) -> None:
    for i, each in enumerate(recorders):
        try:
            each(event)
        except Exception as error:
            later_errors = _finish_all(recorders[:i], RunFinished(event.started_at, "failed"))
            if not later_errors:
                raise
            raise ExceptionGroup("recorders failed", [error, *later_errors]) from None


def _finish_all(recorders: tuple[Recorder, ...], event: RunFinished) -> list[Exception]:
    """Passes `event` to every recorder: their errors."""
    errors: list[Exception] = []
    for each in recorders:
        try:
            each(event)
        except Exception as error:
            errors.append(error)
    return errors


def _raise_all(errors: list[Exception]) -> None:
    if len(errors) == 1:
        raise errors[0]
    if errors:
        raise ExceptionGroup("recorders failed", errors)


@final
@dataclass(frozen=True, slots=True)
class Hint:
    """A finding of `diagnose` about one step occurrence: what limits the run there, and what may help."""

    step_id: StepId
    message: str


_POOL_OVERHEAD_SHARE: Final = 0.3
"""A step's pool tasks have overhead worth a hint if they spent more than this share of their time outside the
user's function."""

_BOTTLENECK_UTILIZATION: Final = 0.7
"""The busiest step limits throughput if it is busy more than this share of its capacity."""


def diagnose(stats: RunStats) -> list[Hint]:
    """Hints derived from a run's statistics (a pure function of `stats`): steps whose pool tasks wait (a
    saturated pool, or slow transport), and the step that limits throughput."""
    hints: list[Hint] = []
    for s in stats.step_stats:
        pool_total_time = s.pool_wait_time + s.pool_running_time
        wait_share = s.pool_wait_time / pool_total_time if pool_total_time > 0 else 0.0
        if s.num_pool_tasks and wait_share > _POOL_OVERHEAD_SHARE:
            hints.append(
                Hint(
                    s.step_id,
                    f"its pool tasks waited {wait_share:.0%} of the time before or around running: "
                    "a saturated pool (more pool workers?) or slow transport",
                )
            )

    def utilization(step_stats: StepStats) -> float:
        return step_stats.utilization

    candidates = [s for s in stats.step_stats if s.num_items_in > 0]
    if candidates and stats.wall_time > 0:
        busiest = max(candidates, key=utilization)
        share = busiest.utilization
        if share > _BOTTLENECK_UTILIZATION and not any(h.step_id == busiest.step_id for h in hints):
            hints.append(
                Hint(busiest.step_id, f"busy {share:.0%} of its capacity: it limits throughput (higher concurrency?)")
            )
    return hints
