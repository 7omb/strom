import pytest

from strom_tools.outlines import Entry, outline, rendered

SOURCE = '''"""The module.

More."""

LIMIT: int = 3
names = ["a"]
type Pair[T] = tuple[T, T]


@dataclass(frozen=True)
class Shards[T](Base, metaclass=Meta):
    """Shards of a stream."""

    size: int

    @classmethod
    def open(cls, *, size: int = 1) -> "Shards[T]":
        """Opens them.

        Details."""
        def inner() -> None: ...

    async def close(self) -> None: ...


if __name__ == "__main__":
    main()
'''


def test_an_outline_lists_the_definitions_of_the_top_level_and_of_classes() -> None:
    assert outline(SOURCE) == [
        Entry(1, 0, "module", "The module."),
        Entry(5, 0, "LIMIT: int = …", None),
        Entry(6, 0, "names = …", None),
        Entry(7, 0, "type Pair = …", None),
        Entry(11, 0, "@dataclass class Shards[T](Base, metaclass=Meta)", "Shards of a stream."),
        Entry(14, 1, "size: int", None),
        Entry(17, 1, "@classmethod def open(cls, *, size: int=1) -> 'Shards[T]'", "Opens them."),
        Entry(23, 1, "async def close(self) -> None", None),
    ], "nested functions and statements are left out"


def test_an_entry_is_a_line_indented_by_its_depth() -> None:
    assert rendered(Entry(17, 1, "def open(cls)", "Opens them.")) == "   17    def open(cls)  # Opens them."
    assert rendered(Entry(5, 0, "LIMIT = …", None)) == "    5  LIMIT = …"


def test_a_module_that_does_not_parse_raises() -> None:
    with pytest.raises(SyntaxError):
        outline("def broken(:\n")
