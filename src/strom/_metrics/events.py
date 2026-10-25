"""Events: step ids and what a run reports to a recorder."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal, final, override

type Part = Literal["left", "right", "body"]
"""The part of an enclosing stage a step is in: a branch of a `product` or `route` stage (its first or its
second stage), or the body of a `gather` or `loop` stage."""


@final
@dataclass(frozen=True, slots=True)
class Enclosing:
    """A `product`, `route`, `gather` or `loop` stage enclosing a step: its position in its chain, its name and
    the part the step is in (a branch, or the body)."""

    index: int
    name: str
    part: Part


@final
@dataclass(frozen=True, slots=True)
class StepId:
    """One occurrence of a step in a run, identified by its position in the run's stage.

    The position is given by the joins, routes, gathers and loops enclosing the step (outermost
    first) and its position in its chain, counted from 1. A chain counts its steps and the stages
    enclosing others in order however it is bracketed; each branch and body counts from 1. `name` and
    `concurrency` describe the step at that position (within a run they follow from it). Shown as e.g.
    `2:product(inc, neg)/left/1:inc`."""

    within: tuple[Enclosing, ...]
    index: int
    name: str
    concurrency: int

    @override
    def __str__(self) -> str:
        enclosing = "".join(f"{each.index}:{each.name}/{each.part}/" for each in self.within)
        return f"{enclosing}{self.index}:{self.name}"


type Outcome = Literal["done", "failed", "cancelled"]
"""How something that ends ended: an input's handling (`InputHandled`) or a run (`RunFinished`).

"done": completed; "failed": its error ends the run (a run: its block raises `RunFailed`); "cancelled": an
input interrupted because the run failed elsewhere, or a run left early (`break`) or cancelled from outside."""


# Events are plain classes with `Final` attributes: read-only for type checkers, and much cheaper to
# construct than frozen dataclasses (one event per input and step).
@final
class RunStarted:
    """A run started at `started_at`: its first event. `steps` are the step occurrences of the (fused) run, in
    the order of its stage; a step that never starts (a run failing early) has no events of its own."""

    __slots__ = ("started_at", "steps")
    __match_args__ = ("started_at", "steps")

    def __init__(self, started_at: float, steps: tuple[StepId, ...]) -> None:
        self.started_at: Final = started_at
        self.steps: Final = steps


@final
class InputHandled:
    """Task `task` (0 to `step_id.concurrency` - 1) of `step_id` took an input and handled it.

    It waited for the input from `wait_started_at` to `started_at` and handled it until `ended_at`;
    `blocked_time` of that went to waiting for downstream to accept its `num_items_out` outputs
    (backpressure). The counts hold whatever the `outcome`: "failed" (its error ends the run) or
    "cancelled" (the run failed elsewhere) also count the outputs already put."""

    __slots__ = (
        "step_id",
        "task",
        "wait_started_at",
        "started_at",
        "ended_at",
        "num_items_out",
        "blocked_time",
        "outcome",
    )
    __match_args__ = (
        "step_id",
        "task",
        "wait_started_at",
        "started_at",
        "ended_at",
        "num_items_out",
        "blocked_time",
        "outcome",
    )

    def __init__(
        self,
        step_id: StepId,
        task: int,
        wait_started_at: float,
        started_at: float,
        ended_at: float,
        num_items_out: int,
        blocked_time: float,
        outcome: Outcome,
    ) -> None:
        self.step_id: Final = step_id
        self.task: Final = task
        self.wait_started_at: Final = wait_started_at
        self.started_at: Final = started_at
        self.ended_at: Final = ended_at
        self.num_items_out: Final = num_items_out
        self.blocked_time: Final = blocked_time
        self.outcome: Final = outcome


@final
class TaskFinished:
    """Task `task` of `step_id` ended at `ended_at`, after waiting for input since `wait_started_at`: its
    input stream ended, it was cancelled (also while waiting), or its last input did not end "done" (then
    `ended_at` is that input's). The last event of the task."""

    __slots__ = ("step_id", "task", "wait_started_at", "ended_at")
    __match_args__ = ("step_id", "task", "wait_started_at", "ended_at")

    def __init__(self, step_id: StepId, task: int, wait_started_at: float, ended_at: float) -> None:
        self.step_id: Final = step_id
        self.task: Final = task
        self.wait_started_at: Final = wait_started_at
        self.ended_at: Final = ended_at


@final
class PoolTaskFinished:
    """A blocking call of `step_id` on a pool completed (a failed one records none: the `InputHandled` of its
    input covers its time).

    It was submitted at `submitted_at` and its result arrived at `ended_at`; `running_time` and `cpu_time`
    are durations measured in the pool worker (another thread, process or host)."""

    __slots__ = ("step_id", "submitted_at", "ended_at", "running_time", "cpu_time")
    __match_args__ = ("step_id", "submitted_at", "ended_at", "running_time", "cpu_time")

    def __init__(
        self, step_id: StepId, submitted_at: float, ended_at: float, running_time: float, cpu_time: float
    ) -> None:
        self.step_id: Final = step_id
        self.submitted_at: Final = submitted_at
        self.ended_at: Final = ended_at
        self.running_time: Final = running_time
        self.cpu_time: Final = cpu_time


@final
class RunFinished:
    """A run ended at `ended_at` with `outcome`: its last event."""

    __slots__ = ("ended_at", "outcome")
    __match_args__ = ("ended_at", "outcome")

    def __init__(self, ended_at: float, outcome: Outcome) -> None:
        self.ended_at: Final = ended_at
        self.outcome: Final = outcome


type Event = RunStarted | InputHandled | TaskFinished | PoolTaskFinished | RunFinished

type Recorder = Callable[[Event], None]
"""Receives the events of a run, in the order they happen and on the event-loop thread.

  * It must not block (a slow recorder stalls the run): an exporter buffers (a list, a `deque`) and exports
    from a task or a thread. It catches its own I/O errors: an error of a recorder is for programming
    errors; it ends the run like an error of a user's function (with the stage note for events of a step)
    and never hides the run's own errors: all are raised in the run's group.
  * A recorder whose `RunStarted` call returned gets exactly one `RunFinished`, the run's last event; one
    that raised gets none. A recorder passing events on to others does the same for them
    (`combine_recorders` does).
  * Per step occurrence and task (`step_id`, `task`): `InputHandled` events, then one `TaskFinished`; each
    `wait_started_at` is the previous `ended_at` of the same task, so idle, busy and blocked time add up to
    the task's lifetime. After a recorder call for a task raised, that task records nothing more.
  * An error recording `PoolTaskFinished` fails the input whose pool task it was: it arrives as that input's
    `InputHandled` with the outcome "failed".
  * `Event` may gain kinds and fields, and `Outcome` values: end a `match` with `case _: pass`, match fields
    by keyword (`case InputHandled(step_id=s)`) and construct events by keyword. New fields go last.
  * Times are readings of `time.perf_counter` on the event loop (monotonic, in seconds, of arbitrary
    origin), except the durations of `PoolTaskFinished`, measured in the pool worker (`time.perf_counter`,
    and `time.thread_time` for CPU time). An exporter needing epoch time anchors it at `RunStarted`
    (`time.perf_counter()` versus `time.time()` at that moment)."""
