"""Tests of `strom._validation`: value constraints that types cannot express."""

from collections.abc import Callable

import pytest
from helpers import inc, to_right

import strom as P


@pytest.mark.parametrize(
    "make_invalid",
    [
        lambda: P.Threads(workers=0),
        lambda: P.Processes(workers=0),
        lambda: P.Pools.open(cpu_workers=0, io_workers=1),
        lambda: P.Pools.open(cpu_workers=1, io_workers=0),
        lambda: P.io_stage(inc, concurrency=0),
        lambda: P.io_stage(inc, buffer_size=0),
        lambda: P.product(P.stage(inc), P.stage(inc), buffer_size=0),
        lambda: P.gather(P.stage(inc), concurrency=0),
        lambda: P.gather(P.stage(inc), buffer_size=0),
        lambda: P.loop(P.stage(to_right), concurrency=0),
        lambda: P.loop(P.stage(to_right), buffer_size=0),
    ],
    ids=[
        "Threads workers=0",
        "Processes workers=0",
        "Pools.open cpu_workers=0",
        "Pools.open io_workers=0",
        "concurrency=0",
        "buffer_size=0",
        "product buffer_size=0",
        "gather concurrency=0",
        "gather buffer_size=0",
        "loop concurrency=0",
        "loop buffer_size=0",
    ],
)
def test_value_constraints(make_invalid: Callable[[], object]) -> None:
    with pytest.raises(ValueError, match=">= 1"):
        make_invalid()
