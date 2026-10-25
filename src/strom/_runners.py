"""The runner `stream`: a run of a stage on its inputs, its outputs as an async iterator.

The block's task group holds one task (`_run`) with the run's own task group, so that leaving the block can
cancel the run; `_Outputs.__anext__` waits for that task at the end of the output queue, because steps end
their queue also when they fail, and after a failure for the end of the block: a consumer inside the block is
cancelled while it waits, one outside it gets an error."""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from time import perf_counter
from typing import Self, final

from strom._interpreters.failures import run_errors, run_failed
from strom._interpreters.fusion import fused
from strom._interpreters.offloaders import RunScope
from strom._interpreters.run_context import Receiver, RunContext, RunState
from strom._interpreters.streaming import start_streaming, step_ids
from strom._metrics.events import Outcome, Recorder, RunFinished, RunStarted
from strom._runtime.pools import Pools, backends_of, check_open
from strom._stages.model import Stage

_STREAM_CLOSED = "the stream is closed: use its outputs inside its `async with` block"
_CONSUMED_OUTSIDE = "the run failed: its error is raised by its `async with` block, where its outputs belong"


def stream[I, O](
    stage: Stage[I, O],
    inputs: Iterable[I] | AsyncIterable[I],
    pools: Pools,
    *,
    recorder: Recorder | None = None,
) -> AbstractAsyncContextManager[AsyncIterator[O]]:
    """A run of `stage` on the items of `inputs`: its outputs, as they come, in no particular order.

        async with stream(stage, inputs, pools) as outputs:
            async for out in outputs: ...

    The body of the `async with` runs in the run's scope, like the body of an asyncio TaskGroup: if
    the run fails, the body is cancelled at its next `await`, and the end of the block raises ONE
    ExceptionGroup ("pipeline run failed") of the errors, including one the body raised. Leaving the
    block early (e.g. `break`) cancels the run without an error.

    `inputs` (an iterable or an async iterable) is iterated on the event loop and belongs to the
    caller: the run does not close it. `recorder` receives the run's events (e.g. a
    `strom.metrics.StatsRecorder`); without one nothing is measured."""
    return _streamed(stage, inputs, pools, recorder)


@asynccontextmanager
async def _streamed[I, O](
    stage: Stage[I, O],
    inputs: Iterable[I] | AsyncIterable[I],
    pools: Pools,
    recorder: Recorder | None,
) -> AsyncGenerator[AsyncIterator[O]]:
    check_open(pools)  # before anything runs, also for a stage without pool steps
    context = RunContext(RunState(), recorder, backends_of(pools), RunScope())  # the run's failure flag, not set
    started_at = perf_counter() if recorder is not None else 0.0  # the run's wall time includes the fusion
    fused_stage = fused(stage)
    if recorder is not None:
        try:
            recorder(RunStarted(started_at, step_ids(fused_stage)))
        except Exception as recorder_error:
            raise run_failed([recorder_error]) from None
    outputs: _Outputs[O] | None = None
    errors: list[BaseException] = []
    outcome: Outcome = "cancelled"  # unless the body ends (left early: cancelled) or the run fails
    try:
        # the body runs in this group's scope: a failing run cancels it, and its error joins the group
        async with asyncio.TaskGroup() as tg:
            ready: asyncio.Future[Receiver[O]] = asyncio.get_running_loop().create_future()
            run_task = tg.create_task(_run(fused_stage, inputs, context, ready))
            outputs = _Outputs(await ready, run_task)
            try:
                yield outputs
            except Exception as error:
                context.state.errors.append(error)  # kept whole by `run_errors` (e.g. the user's own group)
                raise
            if run_task.done():  # not left early (a failure of the run raises below)
                outcome = "done"
            run_task.cancel()  # the body is done (also when it stopped early): so is the run
    except BaseExceptionGroup as group:
        errors = run_errors(group, context.state.errors)
    finally:
        if outputs is not None:
            outputs._close()  # pyright: ignore[reportPrivateUsage]  # no public method on the user's outputs
        if (token := context.scope.used()) is not None:
            try:
                context.backends.release(token)  # every step task has ended: what they left in the workers goes
            except Exception as release_error:  # a backend's error; never hides the run's own errors
                errors.append(release_error)
        if recorder is not None:
            try:
                recorder(RunFinished(perf_counter(), "failed" if errors else outcome))
            except Exception as recorder_error:  # never hides the run's own errors
                errors.append(recorder_error)
    if errors:
        # outside the except block: no implicit chaining to the TaskGroup's group
        raise run_failed(errors)


async def _run[I, O](
    stage: Stage[I, O],
    inputs: Iterable[I] | AsyncIterable[I],
    context: RunContext,
    ready: asyncio.Future[Receiver[O]],
) -> None:
    """The run's own task: the feeder and the stage's tasks, in a task group that `stream` can cancel."""
    async with asyncio.TaskGroup() as tg:
        inq, outq = start_streaming(stage, tg, context)
        tg.create_task(_feed(inputs, inq, context))
        ready.set_result(outq)


async def _feed[I](inputs: Iterable[I] | AsyncIterable[I], inq: asyncio.Queue[I], context: RunContext) -> None:
    """Puts the items of `inputs` into `inq`, then ends the stream.

    Iterates on the event loop, an async iterable with `async for` (also one that is iterable as
    well; checked once per run). An error of the iteration ends the run like a step's error (without
    a stage note: it passed no stage). `inputs` belongs to the caller: it is not closed."""
    try:
        # the put is written out twice: iterating sync inputs through an async adapter costs 0.14 µs per
        # item more (0.52 vs 0.38 µs, 2026-11-05), 2-3% of a run of cheap steps
        match inputs:
            case AsyncIterable():
                async for item in inputs:
                    if inq.full():
                        await inq.put(item)
                    else:
                        inq.put_nowait(item)
            case _:
                for item in inputs:
                    if inq.full():
                        await inq.put(item)
                    else:
                        inq.put_nowait(item)
    except Exception as error:
        context.state.failed.set()
        context.state.errors.append(error)
        raise
    finally:
        inq.shutdown()


@final
class _Outputs[O]:
    """The outputs of a run, for one or several consumers (each output goes to one of them).

    A class, not an async generator: an async generator can't be advanced by two tasks at once."""

    __slots__ = ("_closed", "_left", "_outq", "_run_task")

    def __init__(self, outq: Receiver[O], run_task: asyncio.Task[None]) -> None:
        self._outq = outq
        self._run_task = run_task
        self._closed = False
        self._left: asyncio.Event | None = None  # made by the first consumer that waits for the block's end

    def _close(self) -> None:
        """The runner's, once the block has been left."""
        self._closed = True
        if self._left is not None:
            self._left.set()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> O:
        if self._closed:
            raise RuntimeError(_STREAM_CLOSED)
        outq = self._outq
        if not outq.empty():
            return outq.get_nowait()
        try:
            return await outq.get()
        except asyncio.QueueShutDown:
            pass
        # the steps end their output queue also when they fail: the end of the queue is the end of the
        # stream only once the run has ended without an error
        await asyncio.wait([self._run_task])
        if not self._run_task.cancelled() and self._run_task.exception() is not None:
            # a consumer in the block's scope is cancelled while it waits here: the block cannot be left before
            # the cancellation has reached it (one loop iteration per task group around it)
            if not self._closed:
                if self._left is None:
                    self._left = asyncio.Event()
                await self._left.wait()
            raise RuntimeError(_CONSUMED_OUTSIDE)  # no cancellation came: the consumer is outside the block
        raise StopAsyncIteration
