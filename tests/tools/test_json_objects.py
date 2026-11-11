import json

import pytest

from strom_tools.json_objects import is_list, is_object, member, parsed


def test_parsed_reads_a_json_text() -> None:
    assert parsed('{"a": [1, "b", null]}') == {"a": [1, "b", None]}
    with pytest.raises(json.JSONDecodeError):
        parsed("{not json")


def test_objects_and_lists_are_told_apart() -> None:
    assert is_object({"a": 1}) and not is_object([1]) and not is_object("a") and not is_object(None)
    assert is_list([1]) and not is_list({"a": 1}) and not is_list("a")


def test_member_of_what_is_no_object_is_missing() -> None:
    assert member({"a": {"b": 2}}, "a") == {"b": 2}
    assert member(member({"a": {"b": 2}}, "a"), "b") == 2
    assert member({"a": 1}, "b") is None
    assert member(member({"a": 1}, "a"), "b") is None
    assert member(None, "a") is None
