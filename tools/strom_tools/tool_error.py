"""`ToolError`: what a tool could not do."""


class ToolError(Exception):
    """A tool can't go on; its text is the message for the user. Raised below the entry points, which print it
    and exit with 1 (`strom_tools.commands.command_line.run`)."""
