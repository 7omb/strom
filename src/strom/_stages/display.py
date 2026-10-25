"""How a stage shows itself: the settings in its repr (`Stage.__repr__`)."""

from typing import Never

from strom._stages.model import (
    DEFAULT_BUFFER_SIZE,
    DEFAULT_IN_FLIGHT,
    AsyncExpand,
    Chain,
    Expand,
    FocusedStep,
    Gather,
    Join,
    Leaf,
    Loop,
    Route,
    Stage,
    Step,
    Using,
)


def settings(stage: Stage[Never, object]) -> list[str]:
    """`name: settings` of each step occurrence (in order, lifted ones included) and each `product`, `route`,
    `gather` and `loop` whose placement or limits differ from the defaults: an event-loop step without
    settings of its own does not appear."""
    match stage:
        case Step():
            placement = _placement(stage.leaf)
            own = [] if placement is None else [placement]
            match stage.leaf:
                case Expand(fn=Using(handle_name=handle_name)):
                    own.append(f"using {handle_name}")
                case _:
                    pass
            own += [f"concurrency={stage.concurrency}"] if stage.concurrency != 1 else []
            inferred_or_default = stage.buffer_size in (None, DEFAULT_BUFFER_SIZE)  # event-loop steps: None
            own += [] if inferred_or_default else [f"buffer_size={stage.buffer_size}"]
            return [f"{stage.name}: {', '.join(own)}"] if own else []
        case FocusedStep():
            return settings(stage.step)
        case Chain():
            return settings(stage.head) + settings(stage.tail)
        case Join() | Route():
            own = [f"buffer_size={stage.buffer_size}"] if stage.buffer_size != DEFAULT_BUFFER_SIZE else []
            return settings(stage.left) + settings(stage.right) + ([f"{stage.name}: {own[0]}"] if own else [])
        case Gather() | Loop():
            own = [f"concurrency={stage.concurrency}"] if stage.concurrency != DEFAULT_IN_FLIGHT else []
            own += [f"buffer_size={stage.buffer_size}"] if stage.buffer_size != DEFAULT_BUFFER_SIZE else []
            return settings(stage.body) + ([f"{stage.name}: {', '.join(own)}"] if own else [])
        case _:
            return []  # a repr never raises


def _placement[I, O](leaf: Leaf[I, O]) -> str | None:
    """Where a leaf runs, as the factory prefix says (`async`, `io`, `cpu`); None: on the event loop."""
    match leaf:
        case AsyncExpand():
            return "async"
        case Expand():
            return leaf.resource
