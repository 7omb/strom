"""JSON read as `object` and narrowed step by step, for formats the tools read leniently (Claude Code's hook
events and transcripts, the friction log): a value that is not what a reader expects counts as missing.

A format the tools trust (pytest-benchmark's and pyright's reports) is assigned to a `TypedDict` instead."""

import json
from typing import TypeIs

type JsonObject = dict[str, object]


def parsed(text: str) -> object:
    """The value of a JSON text (`json.JSONDecodeError` if it is none)."""
    value: object = json.loads(text)
    return value


def is_object(value: object) -> TypeIs[JsonObject]:
    """Whether `value` is a JSON object (its keys are strings: it was parsed from JSON)."""
    return isinstance(value, dict)


def is_list(value: object) -> TypeIs[list[object]]:
    return isinstance(value, list)


def member(value: object, key: str) -> object:
    """The member `key` of a JSON object; None if `value` is no object or has none."""
    return value.get(key) if is_object(value) else None
