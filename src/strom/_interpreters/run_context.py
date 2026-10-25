"""What the parts of a streaming run share: its state, its recorder, its backends and scope, the queue view,
and how each of them starts its tasks."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, final

from strom._interpreters.failures import add_stage_note
from strom._interpreters.offloaders import FailureFlag, RunScope
from strom._metrics.events import Recorder
from strom._runtime.pools import RunBackends


class Receiver[T](Protocol):
    """Read-only view of a queue.

    Stages only read from their input queue, so this view is covariant (unlike asyncio.Queue), which
    keeps the variance of Stage sound."""

    async def get(self) -> T: ...

    def get_nowait(self) -> T: ...

    def empty(self) -> bool: ...


@final
@dataclass(frozen=True, slots=True)
class RunState:
    """What a streaming run's parts change: its failure flag (set when it fails; its pool tasks not yet
    started are then skipped) and the errors that ended it, as raised (see `run_errors`)."""

    failed: FailureFlag = field(default_factory=FailureFlag)
    errors: list[BaseException] = field(default_factory=list)


@final
@dataclass(frozen=True, slots=True)
class RunContext:
    """What the parts of a streaming run share: its state, its recorder (None: nothing is measured), its
    backends and its scope (the token of its `io_stage` iterators, which the runner releases through
    `backends` at the run's end)."""

    state: RunState
    recorder: Recorder | None
    backends: RunBackends
    scope: RunScope


def start_tasks[O](
    tg: asyncio.TaskGroup,
    outq: asyncio.Queue[O],
    start: Callable[[asyncio.TaskGroup], None],
    state: RunState,
    *,
    name: str | None,
    ended: Callable[[], None] | None = None,
) -> None:
    """Starts the tasks of one element of a run's stage (a step occurrence, a join, a route, a gather or a
    loop): `start` creates them in a task group of their own, inside a task of `tg`.

    When they have ended, whatever ended them, the stream of `outq` ends. An error among them is noted with
    the stage `name` (None for a step, whose tasks note their errors themselves). `ended` runs once they have
    ended without an error, and what it raises counts as an error of theirs (a join's check that every input
    is complete)."""

    async def run_tasks() -> None:
        try:
            async with asyncio.TaskGroup() as inner_tg:
                start(inner_tg)
            if ended is not None:
                ended()
        except Exception as error:
            if name is not None:
                add_stage_note(error, name, state.errors)
            raise
        finally:
            outq.shutdown()  # end of stream for downstream

    tg.create_task(run_tasks())
