"""`strom_tools.commands.outline` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import command_line, outline

if __name__ == "__main__":
    sys.exit(command_line.run(outline.main))
