"""`ToolError`: what a tool could not do."""


class ToolError(Exception):
    """A tool can't go on; its text is the message for the user. Raised below the entry points: a command prints
    it and exits with `DID_NOT_RUN` (`strom_tools.commands.command_line.run`), a hook reports it as failed."""
