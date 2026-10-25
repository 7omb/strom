"""Closing iterators that may be closable: for the interpreters and the pool workers alike."""

from collections.abc import Awaitable, Callable


def close_if_closable(iterator: object) -> None:
    """Closes `iterator` if it has a `close` method (generators, files, ...)."""
    # getattr instead of `isinstance` with a runtime-checkable Protocol: that check takes
    # microseconds when it fails (e.g. for a tuple iterator, i.e. for most 1:1 functions), getattr
    # about 30 ns. Type safety is unchanged: the Protocol check also only tests that the name
    # exists, so the declared type of `close` was an unchecked assumption before as well. getattr
    # with a None default is typed `Any | None`, which the annotation narrows without an ignore.
    close: Callable[[], object] | None = getattr(iterator, "close", None)
    if close is not None:
        close()


async def aclose_if_closable(aiterator: object) -> None:
    """Closes `aiterator` if it has an `aclose` method (async generators, ...); see `close_if_closable`."""
    aclose: Callable[[], Awaitable[object]] | None = getattr(aiterator, "aclose", None)
    if aclose is not None:
        await aclose()
