"""The streaming interpreter: a run's stage as tasks and bounded queues; chains, joins, routes, gathers and
loops here, steps in `steps`."""

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import assert_never

from strom._interpreters.run_context import Receiver, RunContext, start_tasks
from strom._interpreters.steps import inferred_queue_size, run_streaming_focused, run_streaming_step
from strom._metrics.events import Enclosing, StepId
from strom._stages.focus import Sequenced
from strom._stages.lifting import lift_sequenced
from strom._stages.model import Chain, FocusedStep, Gather, Join, Left, Loop, Right, Route, Stage, Step


class _PendingInput[B, D, T]:
    """What a join keeps of one input until it is complete.

    Its kept value, the results of each branch received while the other branch may still deliver
    results to merge them with, and the number of the input's items inside each branch."""

    __slots__ = ("kept", "lefts", "rights", "num_left_inside", "num_right_inside")

    def __init__(self, kept: T) -> None:
        self.kept = kept
        self.lefts: list[B] = []
        self.rights: list[D] = []
        self.num_left_inside = self.num_right_inside = 1  # its branch input


async def _put_both[A, C](left: asyncio.Queue[A], a: A, right: asyncio.Queue[C], c: C) -> None:
    """Puts `a` into `left` and `c` into `right`.

    A full queue delays only its own put, so a branch with room gets its input without waiting for
    the other branch. Measured: opposite-phase bursts of 4 slow items (4 ms), `buffer_size=1`: 2.74 →
    2.25 ms per item."""
    left_full = right_full = False
    try:
        left.put_nowait(a)
    except asyncio.QueueFull:
        left_full = True
    try:
        right.put_nowait(c)
    except asyncio.QueueFull:
        right_full = True
    if left_full and right_full:
        await asyncio.gather(left.put(a), right.put(c))
    elif left_full:
        await left.put(a)
    elif right_full:
        await right.put(c)


async def _forward[B, O](branch_outq: Receiver[B], from_branch: Callable[[B], O], outq: asyncio.Queue[O]) -> None:
    """Puts from_branch(b) into `outq` for each output b of a route's branch, until its end of stream."""
    while True:
        try:
            b = branch_outq.get_nowait() if not branch_outq.empty() else await branch_outq.get()
        except asyncio.QueueShutDown:
            return
        out = from_branch(b)
        if not outq.full():
            outq.put_nowait(out)
        else:
            await outq.put(out)


class _InFlightInput[K]:
    """What `_InFlight` keeps of one input: its kept value and the number of its items inside the body."""

    __slots__ = ("kept", "num_inside")

    def __init__(self, kept: K) -> None:
        self.kept = kept
        self.num_inside = 1  # its body input


class _InFlight[I, A, K]:
    """The inputs in flight of a gather or a loop: at most `concurrency`, each from being taken until
    the gather or loop calls `release`.

    `admit` (the split loop) takes the inputs, gives each a sequence number and puts its body input
    into `body_inq`; `count` (the `Count` of the body's steps, see `lift_sequenced`) counts each
    input's items inside the body and calls `complete` once there are none. `body_inq` must be
    unbounded (it holds the items of the inputs in flight, so putting never waits); it is shut down,
    ending the body's input stream, once upstream has ended and no input is inside the body any more."""

    __slots__ = ("_split", "_complete", "_body_inq", "_slots", "_inputs", "_upstream_done")

    def __init__(
        self,
        split: Callable[[I], tuple[A, K]],
        concurrency: int,
        complete: Callable[[int, K], None],
        body_inq: asyncio.Queue[Sequenced[A]],
    ) -> None:
        self._split = split
        self._complete = complete
        self._body_inq = body_inq
        self._slots = asyncio.Semaphore(concurrency)
        self._inputs: dict[int, _InFlightInput[K]] = {}  # inputs with items inside the body
        self._upstream_done = False

    def count(self, sequence: int, delta: int) -> None:
        admitted = self._inputs[sequence]
        admitted.num_inside += delta
        if admitted.num_inside == 0:
            del self._inputs[sequence]
            self._complete(sequence, admitted.kept)
            if self._upstream_done and not self._inputs:
                self._body_inq.shutdown()

    def kept(self, sequence: int) -> K:
        """The kept value of an input with items inside the body."""
        return self._inputs[sequence].kept

    def release(self) -> None:
        """Ends an input's time in flight: `admit` may take another one."""
        self._slots.release()

    async def admit(self, inq: Receiver[I]) -> None:
        """The split loop: takes an input only while fewer than `concurrency` are in flight."""
        sequence = 0
        try:
            while True:
                await self._slots.acquire()  # before taking: an input waiting for a slot stays upstream
                try:
                    item = inq.get_nowait() if not inq.empty() else await inq.get()
                except asyncio.QueueShutDown:
                    return
                a, kept = self._split(item)
                self._inputs[sequence] = _InFlightInput(kept)
                self._body_inq.put_nowait((a, sequence))
                sequence += 1
        finally:
            self._upstream_done = True
            if not self._inputs:
                self._body_inq.shutdown()


def start_streaming[I, O](
    stage: Stage[I, O], tg: asyncio.TaskGroup, context: RunContext
) -> tuple[asyncio.Queue[I], Receiver[O]]:
    """Starts the tasks of a run of `stage` in `tg`: the queue to put the run's inputs into (sized for
    the stage's intake; ending it ends the run's stream) and the run's outputs."""
    inq: asyncio.Queue[I] = asyncio.Queue(maxsize=inferred_queue_size(_intake(stage)))
    outq, _ = _run_streaming(stage, tg, inq, context, (), 1, 1)  # the root position; one consumer
    return inq, outq


def _run_streaming[I, O](
    stage: Stage[I, O],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
    consumer_concurrency: int,
) -> tuple[Receiver[O], int]:
    """Streaming execution: starts the stage's tasks reading `inq`.

    `within` and `index` are the position of the stage's first element (see `StepId`);
    `consumer_concurrency` is the concurrency of the part that takes the stage's outputs (sizes
    inferred queues, see `strom._interpreters.steps`). Returns the output queue and the index following the
    stage's last element."""
    match stage:
        case Step():
            return (run_streaming_step(stage, tg, inq, context, within, index, consumer_concurrency), index + 1)
        case FocusedStep():
            return (run_streaming_focused(stage, tg, inq, context, within, index, consumer_concurrency), index + 1)
        case Chain():
            return _run_streaming_chain(stage, tg, inq, context, within, index, consumer_concurrency)
        case Join():
            return _run_streaming_join(stage, tg, inq, context, within, index), index + 1
        case Route():
            return _run_streaming_route(stage, tg, inq, context, within, index), index + 1
        case Gather():
            return _run_streaming_gather(stage, tg, inq, context, within, index), index + 1
        case Loop():
            return _run_streaming_loop(stage, tg, inq, context, within, index), index + 1
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def step_ids[I, O](stage: Stage[I, O]) -> tuple[StepId, ...]:
    """The step occurrences of a run of `stage` (fused), in the order of the stage: the positions
    `_run_streaming` gives them, without starting anything (joins, routes, gathers and loops start their parts
    only once they run)."""
    found: list[StepId] = []
    _add_step_ids(stage, (), 1, found)
    return tuple(found)


def _add_step_ids[I, O](stage: Stage[I, O], within: tuple[Enclosing, ...], index: int, found: list[StepId]) -> int:
    """Adds the step ids of `stage` at the position (`within`, `index`) of its first element to `found`; the
    index following its last element, as `_run_streaming`."""
    match stage:
        case Step():
            found.append(StepId(within, index, stage.name, stage.concurrency))
        case FocusedStep():
            found.append(StepId(within, index, stage.step.name, stage.step.concurrency))
        case Chain():
            return _add_step_ids(stage.tail, within, _add_step_ids(stage.head, within, index, found), found)
        case Join() | Route():
            _add_step_ids(stage.left, (*within, Enclosing(index, stage.name, "left")), 1, found)
            _add_step_ids(stage.right, (*within, Enclosing(index, stage.name, "right")), 1, found)
        case Gather() | Loop():
            _add_step_ids(stage.body, (*within, Enclosing(index, stage.name, "body")), 1, found)
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")
    return index + 1


def _run_streaming_chain[I, M, O](
    chain: Chain[I, M, O],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
    consumer_concurrency: int,
) -> tuple[Receiver[O], int]:
    middleq, index = _run_streaming(chain.head, tg, inq, context, within, index, _intake(chain.tail))
    return _run_streaming(chain.tail, tg, middleq, context, within, index, consumer_concurrency)


def _intake[I, O](stage: Stage[I, O]) -> int:
    """How many inputs `stage` takes at once: the concurrency of its first step.

    1 for a join, a route, a gather or a loop, whose split loop takes them one by one."""
    match stage:
        case Step():
            return stage.concurrency
        case FocusedStep():
            return stage.step.concurrency
        case Chain():
            return _intake(stage.head)
        case Join() | Route() | Gather() | Loop():
            return 1
        case _:
            raise TypeError(f"unknown stage kind {type(stage).__name__}")


def _run_streaming_join[I, O, A, B, C, D, T](
    join: Join[I, O, A, B, C, D, T],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
) -> Receiver[O]:
    """Streams the parts of each input through the two branches and joins their results.

    The focus splits each input into ((a, c), t); a and c get the input's sequence number and are
    streamed through the two branches independently (every step with its own concurrency). Each
    result is merged at once with the other branch's results of the same input received so far (a
    symmetric hash join). The steps of each branch count the items of each input inside it
    (`lift_sequenced`). A branch holding no item of an input any more is done with it: the other
    branch's results of the input are no longer kept. When both are done, the input is complete:
    its state is dropped and the focus finishes t."""
    name, split, merge, finish = join.name, join.focus.split, join.focus.merge, join.focus.finish
    # inputs not yet complete; their number is bounded by the capacity of the branches, because
    # `split_items` waits until both branches accept an item
    pending: dict[int, _PendingInput[B, D, T]] = {}

    def count_left(sequence: int, delta: int) -> None:
        state = pending[sequence]
        state.num_left_inside += delta
        if state.num_left_inside == 0:  # no more left results to merge the right ones with
            state.rights = []
            if state.num_right_inside == 0:
                del pending[sequence]
                if finish is not None:
                    finish(state.kept)

    def count_right(sequence: int, delta: int) -> None:
        state = pending[sequence]
        state.num_right_inside += delta
        if state.num_right_inside == 0:  # no more right results to merge the left ones with
            state.lefts = []
            if state.num_left_inside == 0:
                del pending[sequence]
                if finish is not None:
                    finish(state.kept)

    left: Stage[Sequenced[A], Sequenced[B]] = lift_sequenced(join.left, count_left)
    right: Stage[Sequenced[C], Sequenced[D]] = lift_sequenced(join.right, count_right)
    left_within = (*within, Enclosing(index, name, "left"))
    right_within = (*within, Enclosing(index, name, "right"))
    outq: asyncio.Queue[O] = asyncio.Queue(maxsize=join.buffer_size)
    left_inq: asyncio.Queue[Sequenced[A]] = asyncio.Queue(maxsize=join.buffer_size)
    right_inq: asyncio.Queue[Sequenced[C]] = asyncio.Queue(maxsize=join.buffer_size)

    async def split_items() -> None:
        try:
            sequence = 0
            while True:
                try:
                    # the join's loops take and put without a coroutine when no wait is needed, like a step
                    (a, c), t = split(inq.get_nowait() if not inq.empty() else await inq.get())
                except asyncio.QueueShutDown:
                    return
                pending[sequence] = _PendingInput[B, D, T](t)
                await _put_both(left_inq, (a, sequence), right_inq, (c, sequence))
                sequence += 1
        finally:
            left_inq.shutdown()
            right_inq.shutdown()

    # A result is merged before it is counted as received: a lifted join counts its outputs in
    # `merge`, so they must be counted before its completion in `finish`. Each pair is merged when it
    # can be put, so at most the output queue's capacity and one pair are in flight.
    async def merge_left(branch_outq: Receiver[Sequenced[B]]) -> None:
        while True:
            try:
                b, sequence = branch_outq.get_nowait() if not branch_outq.empty() else await branch_outq.get()
            except asyncio.QueueShutDown:
                return
            state = pending[sequence]
            if state.num_right_inside:
                state.lefts.append(b)
            rights = state.rights  # a count may replace it with an empty list meanwhile, never clears it
            for i in range(len(rights)):  # results arriving meanwhile pair with b themselves
                out = merge((b, rights[i]), state.kept)  # counted (a lifted join) right before its put
                if not outq.full():
                    outq.put_nowait(out)
                else:
                    await outq.put(out)
            count_left(sequence, -1)  # after its pairs are put: the input stays pending meanwhile

    async def merge_right(branch_outq: Receiver[Sequenced[D]]) -> None:
        while True:
            try:
                d, sequence = branch_outq.get_nowait() if not branch_outq.empty() else await branch_outq.get()
            except asyncio.QueueShutDown:
                return
            state = pending[sequence]
            if state.num_left_inside:
                state.rights.append(d)
            lefts = state.lefts  # a count may replace it with an empty list meanwhile, never clears it
            for i in range(len(lefts)):  # results arriving meanwhile pair with d themselves
                out = merge((lefts[i], d), state.kept)  # counted (a lifted join) right before its put
                if not outq.full():
                    outq.put_nowait(out)
                else:
                    await outq.put(out)
            count_right(sequence, -1)  # after its pairs are put: the input stays pending meanwhile

    def start(inner_tg: asyncio.TaskGroup) -> None:
        inner_tg.create_task(split_items())
        # each branch's outputs are taken by one merge loop
        left_outq, _ = _run_streaming(left, inner_tg, left_inq, context, left_within, 1, 1)
        right_outq, _ = _run_streaming(right, inner_tg, right_inq, context, right_within, 1, 1)
        inner_tg.create_task(merge_left(left_outq))
        inner_tg.create_task(merge_right(right_outq))

    def check_complete() -> None:
        if pending:  # every item of a branch is counted, so every input completes
            raise AssertionError(f"product {name!r}: {len(pending)} inputs not complete")

    start_tasks(tg, outq, start, context.state, name=name, ended=check_complete)
    return outq


def _run_streaming_route[I, O, A, B, C, D](
    route: Route[I, O, A, B, C, D],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
) -> Receiver[O]:
    """Streams each input through the branch it chooses; each branch's outputs are passed on as they come.

    A full branch queue holds back the split loop, as a full step queue holds back a step."""
    name, choose = route.name, route.choose
    left_within = (*within, Enclosing(index, name, "left"))
    right_within = (*within, Enclosing(index, name, "right"))
    outq: asyncio.Queue[O] = asyncio.Queue(maxsize=route.buffer_size)
    left_inq: asyncio.Queue[A] = asyncio.Queue(maxsize=route.buffer_size)
    right_inq: asyncio.Queue[C] = asyncio.Queue(maxsize=route.buffer_size)

    async def split_items() -> None:
        try:
            while True:
                try:
                    item = inq.get_nowait() if not inq.empty() else await inq.get()
                except asyncio.QueueShutDown:
                    return
                match choose(item):
                    case Left(a):
                        if not left_inq.full():
                            left_inq.put_nowait(a)
                        else:
                            await left_inq.put(a)
                    case Right(c):
                        if not right_inq.full():
                            right_inq.put_nowait(c)
                        else:
                            await right_inq.put(c)
                    case unknown:  # untyped code: an item that is not tagged must not vanish
                        assert_never(unknown)
        finally:
            left_inq.shutdown()
            right_inq.shutdown()

    def start(inner_tg: asyncio.TaskGroup) -> None:
        inner_tg.create_task(split_items())
        # each branch's outputs are taken by one forward loop
        left_outq, _ = _run_streaming(route.left, inner_tg, left_inq, context, left_within, 1, 1)
        right_outq, _ = _run_streaming(route.right, inner_tg, right_inq, context, right_within, 1, 1)
        inner_tg.create_task(_forward(left_outq, route.from_left, outq))
        inner_tg.create_task(_forward(right_outq, route.from_right, outq))

    start_tasks(tg, outq, start, context.state, name=name)
    return outq


def _run_streaming_gather[I, O, A, B, K](
    gather: Gather[I, O, A, B, K],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
) -> Receiver[O]:
    """Streams each input through the body and emits the list of its outputs once the input is complete.

    The body's steps count the items of each input inside it (`lift_sequenced`, as in a join's
    branch). An input may complete in a body step's `finish` (an item without outputs), where nothing
    can be put, so completed inputs go through a ready queue to the loop that emits them. An input
    stays in flight until its list is put: otherwise, while the output queue is full, inputs whose
    items the body drops would complete, and their lists collect, without bound."""
    name, merge, finish = gather.name, gather.focus.merge, gather.focus.finish
    outputs_of: defaultdict[int, list[B]] = defaultdict(list)  # of each input in flight, so far
    # both unbounded: they hold at most the inputs in flight
    body_inq: asyncio.Queue[Sequenced[A]] = asyncio.Queue()
    readyq: asyncio.Queue[tuple[list[B], K]] = asyncio.Queue()
    outq: asyncio.Queue[O] = asyncio.Queue(maxsize=gather.buffer_size)

    def complete(sequence: int, kept: K) -> None:
        readyq.put_nowait((outputs_of.pop(sequence, []), kept))

    in_flight = _InFlight(gather.focus.split, gather.concurrency, complete, body_inq)
    body: Stage[Sequenced[A], Sequenced[B]] = lift_sequenced(gather.body, in_flight.count)
    body_within = (*within, Enclosing(index, name, "body"))

    async def collect_outputs(body_outq: Receiver[Sequenced[B]]) -> None:
        while True:
            try:
                b, sequence = body_outq.get_nowait() if not body_outq.empty() else await body_outq.get()
            except asyncio.QueueShutDown:
                # The body's tasks ended: no input completes any more. Not when cancelled: the body's
                # steps may still complete inputs then, in their `finish`.
                readyq.shutdown()
                return
            outputs_of[sequence].append(b)
            in_flight.count(sequence, -1)

    async def emit() -> None:
        while True:
            try:
                outputs, kept = readyq.get_nowait() if not readyq.empty() else await readyq.get()
            except asyncio.QueueShutDown:
                return
            out = merge(outputs, kept)  # counted (a lifted gather) before its put, as in a step
            if not outq.full():
                outq.put_nowait(out)
            else:
                await outq.put(out)
            if finish is not None:
                finish(kept)
            in_flight.release()

    def start(inner_tg: asyncio.TaskGroup) -> None:
        inner_tg.create_task(in_flight.admit(inq))
        # the body's outputs are taken by one collect loop
        body_outq, _ = _run_streaming(body, inner_tg, body_inq, context, body_within, 1, 1)
        inner_tg.create_task(collect_outputs(body_outq))
        inner_tg.create_task(emit())

    start_tasks(tg, outq, start, context.state, name=name)
    return outq


def _run_streaming_loop[I, O, A, B, K](
    loop: Loop[I, O, A, B, K],
    tg: asyncio.TaskGroup,
    inq: Receiver[I],
    context: RunContext,
    within: tuple[Enclosing, ...],
    index: int,
) -> Receiver[O]:
    """Streams each input through the body; the body's `Left` outputs go back into it, its `Right`
    outputs are emitted.

    The loop has no wait cycle: the body's input queue is unbounded, so feeding an item back never
    waits; the loop waits only for the output queue, outside it. The number of inputs in flight bounds
    the queue instead: only their items circulate. It is a LIFO queue: the newest item, fed back or
    newly admitted, enters the body first (the queues inside the body stay FIFO, so the order is not
    the reference semantics' depth-first one). The body's steps count the items of each
    input inside it (`lift_sequenced`); an input is complete, and leaves the loop, when there are
    none. The body's input stream ends when upstream has ended and no input is in flight."""
    name, merge, finish = loop.name, loop.focus.merge, loop.focus.finish
    body_inq: asyncio.LifoQueue[Sequenced[A]] = asyncio.LifoQueue()
    outq: asyncio.Queue[O] = asyncio.Queue(maxsize=loop.buffer_size)

    def complete(_: int, kept: K) -> None:
        if finish is not None:
            finish(kept)
        in_flight.release()

    in_flight = _InFlight(loop.focus.split, loop.concurrency, complete, body_inq)
    body: Stage[Sequenced[A], Sequenced[Left[A] | Right[B]]] = lift_sequenced(loop.body, in_flight.count)
    body_within = (*within, Enclosing(index, name, "body"))

    async def feed_back(body_outq: Receiver[Sequenced[Left[A] | Right[B]]]) -> None:
        while True:
            try:
                tagged, sequence = body_outq.get_nowait() if not body_outq.empty() else await body_outq.get()
            except asyncio.QueueShutDown:
                return
            match tagged:
                case Left(a):
                    body_inq.put_nowait((a, sequence))  # stays inside the body: its count is unchanged
                case Right(b):
                    out = merge(b, in_flight.kept(sequence))  # counted (a lifted loop) before its put
                    if not outq.full():
                        outq.put_nowait(out)
                    else:
                        await outq.put(out)
                    in_flight.count(sequence, -1)  # after its put: the input stays in flight meanwhile
                case unknown:  # untyped code: an output that is not tagged must not vanish
                    assert_never(unknown)

    def start(inner_tg: asyncio.TaskGroup) -> None:
        inner_tg.create_task(in_flight.admit(inq))
        # the body's outputs are taken by one feedback loop
        body_outq, _ = _run_streaming(body, inner_tg, body_inq, context, body_within, 1, 1)
        inner_tg.create_task(feed_back(body_outq))

    start_tasks(tg, outq, start, context.state, name=name)
    return outq
