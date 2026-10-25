"""Failures: the note naming a stage on an error, the errors that ended a run, and the group a failed run
raises (both interpreters)."""

from collections.abc import Sequence
from typing import final, override

_RUN_FAILED = "pipeline run failed"


def stage_note(name: str) -> str:
    """The note naming a stage on an error that passed it (a failing step, an enclosing combinator)."""
    return f"in stage {name!r}"


def run_errors(error: BaseException, recorded: list[BaseException]) -> list[BaseException]:
    """The errors in `error` that ended a run, as raised: an error of `recorded` (one that a step's
    `failing` recorded, e.g. a user's own exception group) is kept whole, the groups of the run's task groups
    around them are removed; any other error is kept as well (e.g. the join's completeness check)."""
    if any(error is each for each in recorded) or not isinstance(error, BaseExceptionGroup):
        return [error]
    return [each for sub in error.exceptions for each in run_errors(sub, recorded)]


def add_stage_note(error: BaseException, name: str, recorded: list[BaseException]) -> None:
    """Names the stage on the run's errors in `error` (see `run_errors`)."""
    note = stage_note(name)
    for each in run_errors(error, recorded):
        each.add_note(note)


@final
class RunFailed(ExceptionGroup[Exception]):
    """The ONE group a failed run raises ("pipeline run failed"): the errors that ended it, as raised.

    `except*` works as for any group; `except RunFailed` (or `pytest.raises(RunFailed)`) tells a
    run's failure from other groups. A split by `except*` keeps the type (`derive`)."""

    @override  # with the narrower type: this group holds `Exception`s only
    def derive(self, excs: Sequence[Exception]) -> RunFailed:  # type: ignore[override]  # pyright: ignore[reportIncompatibleMethodOverride]
        return RunFailed(self.message, excs)


def run_failed(errors: list[BaseException]) -> BaseExceptionGroup[BaseException]:
    """The group of a failed run (`stream`) or evaluation (`evaluate`): a `RunFailed`, or a plain group if an
    error is no `Exception`."""
    exceptions = [error for error in errors if isinstance(error, Exception)]
    if len(exceptions) == len(errors):
        return RunFailed(_RUN_FAILED, exceptions)
    return BaseExceptionGroup(_RUN_FAILED, errors)
