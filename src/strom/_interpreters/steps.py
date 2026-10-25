"""The steps of a streaming run: their tasks, how they record, and the sizes of their output queues."""

import asyncio
from collections.abc import Callable
from time import perf_counter
from typing import Final, Never, final

from strom._closing import aclose_if_closable
from strom._interpreters.failures import stage_note
from strom._interpreters.item_fns import ItemFn, item_fn_of
from strom._interpreters.offloaders import PoolTaskSkipped, step_offloader
from strom._interpreters.run_context import Receiver, RunContext, RunState, start_tasks
from strom._metrics.events import Enclosing, Event, InputHandled, Outcome, Recorder, StepId, TaskFinished
from strom._stages.focus import Focus, same_focus
from strom._stages.model import DEFAULT_BUFFER_SIZE, FocusedStep, Step


def run_streaming_step[I, O](
    step: Step[I, O],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
    consumer_concurrency: int,
) -> Receiver[O]:
    step_id = StepId(within, index, step.name, step.concurrency)
    offloader = step_offloader(context.backends, context.state.failed, context.scope, context.recorder, step_id)
    item_fn = item_fn_of(step.leaf, offloader)
    focus: Focus[I, O, I, O, None] = same_focus()
    queue_size = _queue_size(step, consumer_concurrency)
    return _run_step_tasks(item_fn, focus, step_id, queue_size, tg, inq, context)


def run_streaming_focused[I, O, A, B, K](
    focused: FocusedStep[I, O, A, B, K],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
    consumer_concurrency: int,
) -> Receiver[O]:
    step = focused.step
    step_id = StepId(within, index, step.name, step.concurrency)
    offloader = step_offloader(context.backends, context.state.failed, context.scope, context.recorder, step_id)
    leaf_item_fn = item_fn_of(step.leaf, offloader)
    queue_size = _queue_size(step, consumer_concurrency)
    return _run_step_tasks(leaf_item_fn, focused.focus, step_id, queue_size, tg, inq, context)


def _queue_size[I, O](step: Step[I, O], consumer_concurrency: int) -> int:
    """The size of a step's output queue.

    Its `buffer_size`, or, if that is None (event-loop steps), the inferred size."""
    if step.buffer_size is not None:
        return step.buffer_size
    return inferred_queue_size(consumer_concurrency)


def inferred_queue_size(consumer_concurrency: int) -> int:
    """The size of a queue filled by a part that never waits (an event-loop step, a run's inputs).

    Twice the concurrency of the part taking its items, enough to keep its tasks busy, but never
    less than the default."""
    return max(DEFAULT_BUFFER_SIZE, 2 * consumer_concurrency)


# How queued pool tasks are skipped after a failure (`PoolTaskSkipped`):
#   1. A failing step sets the run's failure flag (`failing`) right before its error is raised; the error
#      ends the run.
#   2. Every pool task of the run is guarded (`strom._interpreters.offloaders`): in its worker it raises
#      `PoolTaskSkipped` instead of calling the user's function once the flag is set, and sets the flag itself
#      when the function raises. A worker in another process has the flag as it was when the task was pickled;
#      cancelling the run cancels queued tasks anyway.
#   3. A step task catching `PoolTaskSkipped` parks in `_until_cancelled` until the run's error cancels it.
#      Raising instead could cancel the task delivering the user's error (Hypothesis found that in about 1
#      in 100 runs of a source of `[0, 7, 0]` `| io_stage(fail_on_7, concurrency=4) | io_stage(double,
#      buffer_size=1)`); returning would end the step's stream early, looking complete downstream (e.g. to
#      `product`).
def _step_failing(state: RunState, name: str) -> Callable[[Exception], None]:
    """What a step does with an error that ends the run (see above)."""

    def failing(error: Exception) -> None:
        state.failed.set()
        state.errors.append(error)
        error.add_note(stage_note(name))

    return failing


async def _until_cancelled() -> Never:
    """Parks a step task whose pool task was skipped (see `_step_failing`)."""
    await asyncio.Event().wait()  # never set
    raise AssertionError("unreachable: the event is never set")


def _unreachable(_: object) -> Never:
    """Stands in for the recorder without one: every use is under `if recording`."""
    raise AssertionError("not recording")


@final
class _StepRecording:
    """The events of a step occurrence's tasks (only used when its run records), each for task `task`; an
    error of the recorder ends the run like a user's error (see `Recorder`), and the task records nothing
    more."""

    __slots__ = ("_failing", "_record", "_step_id")

    def __init__(self, step_id: StepId, record: Recorder, failing: Callable[[Exception], None]) -> None:
        self._step_id = step_id
        self._record: Final = record
        self._failing = failing

    def _record_or_fail(self, event: Event) -> None:
        try:
            self._record(event)
        except Exception as error:
            self._failing(error)
            raise

    def task_finished(self, task: int, wait_started_at: float, ended_at: float) -> None:
        self._record_or_fail(TaskFinished(self._step_id, task, wait_started_at, ended_at))

    def handled(
        self,
        task: int,
        wait_started_at: float,
        started_at: float,
        ended_at: float,
        num_items_out: int,
        blocked_time: float,
    ) -> None:
        """Records an input handled to its end ("done")."""
        self._record_or_fail(
            InputHandled(
                self._step_id, task, wait_started_at, started_at, ended_at, num_items_out, blocked_time, "done"
            )
        )

    def aborted(
        self,
        task: int,
        wait_started_at: float,
        started_at: float,
        ended_at: float,
        num_items_out: int,
        blocked_time: float,
        error: Exception | None,
    ) -> None:
        """Records an input whose handling `error` failed (already `failing`) or, if None, the run's failure
        elsewhere cancelled, and the end of its task; an error of the recorder keeps the user's."""
        step_id = self._step_id
        outcome: Outcome = "cancelled" if error is None else "failed"
        try:
            self._record(
                InputHandled(step_id, task, wait_started_at, started_at, ended_at, num_items_out, blocked_time, outcome)
            )
            self._record(TaskFinished(step_id, task, ended_at, ended_at))
        except Exception as recorder_error:
            self._failing(recorder_error)
            if error is None:
                raise
            raise ExceptionGroup("recording a failure failed", [error, recorder_error])  # noqa: B904 (holds both)


def _run_step_tasks[I, O, A, B, K](
    leaf_item_fn: ItemFn[A, B],
    focus: Focus[I, O, A, B, K],
    step_id: StepId,
    queue_size: int,
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
) -> Receiver[O]:
    """The tasks of a step occurrence: each takes one input after another and handles it.

    A task applies `focus` and the leaf's ItemFn to the input and puts the outputs. One loop for
    every step, recorded or not: the checks of `recording` are cheap, and the queues are used without
    a coroutine when no wait is needed."""
    outq: asyncio.Queue[O] = asyncio.Queue(maxsize=queue_size)  # owned by the producer
    recorder = context.recorder  # checked once per run
    recording = recorder is not None
    failing = _step_failing(context.state, step_id.name)
    events = _StepRecording(step_id, _unreachable if recorder is None else recorder, failing)

    async def task(index: int) -> None:
        # When recording, every input taken records one InputHandled: "done", "failed" (its error ends the
        # run) or "cancelled" (the run failed elsewhere: cancelled, or its pool task skipped). The task's end
        # records one TaskFinished: its input stream ended, it was cancelled while waiting for input, or right
        # after an input not "done". An input's end, read once, is the next wait's start: idle, busy and
        # blocked time add up to the task's lifetime. Only puts that wait for downstream count as blocked, a
        # cancelled one until its cancellation.
        is_recording, split, merge, finish, clock = recording, focus.split, focus.merge, focus.finish, perf_counter
        wait_started_at = clock() if is_recording else 0.0
        started_at = 0.0
        put_started_at: float | None = None  # while a recorded put waits
        while True:
            try:  # wait for input BEFORE touching the pool
                item = inq.get_nowait() if not inq.empty() else await inq.get()
            except asyncio.QueueShutDown:  # upstream finished and drained
                if is_recording:
                    events.task_finished(index, wait_started_at, clock())
                return
            except BaseException:  # cancelled while waiting: the run failed elsewhere
                if is_recording:
                    events.task_finished(index, wait_started_at, clock())
                raise
            if is_recording:
                started_at = clock()
            num_items_out, blocked_time = 0, 0.0
            try:
                try:
                    a, kept = split(item)
                    outs = leaf_item_fn(a)
                    try:
                        async for b in outs:
                            out = merge(b, kept)
                            if not outq.full():
                                outq.put_nowait(out)
                            elif is_recording:
                                put_started_at = clock()
                                await outq.put(out)
                                blocked_time += clock() - put_started_at
                                put_started_at = None
                            else:
                                await outq.put(out)
                            num_items_out += 1
                    except BaseException:  # stopped early (also cancelled): close at once (see the focuses)
                        await aclose_if_closable(outs)
                        raise
                    finally:
                        if finish is not None:
                            finish(kept)
                except PoolTaskSkipped:  # another item of this run failed: its error cancels this one
                    await _until_cancelled()
            except Exception as error:
                ended_at = clock() if is_recording else 0.0
                failing(error)
                if is_recording:
                    events.aborted(index, wait_started_at, started_at, ended_at, num_items_out, blocked_time, error)
                raise
            except BaseException:  # cancelled: the run failed elsewhere
                if is_recording:
                    ended_at = clock()
                    if put_started_at is not None:
                        blocked_time += ended_at - put_started_at
                    events.aborted(index, wait_started_at, started_at, ended_at, num_items_out, blocked_time, None)
                raise
            if is_recording:
                ended_at = clock()
                events.handled(index, wait_started_at, started_at, ended_at, num_items_out, blocked_time)
                wait_started_at = ended_at

    def start(inner_tg: asyncio.TaskGroup) -> None:
        for index in range(step_id.concurrency):
            inner_tg.create_task(task(index))

    start_tasks(tg, outq, start, context.state, name=None)  # `failing` notes a step's errors where they are raised
    return outq
