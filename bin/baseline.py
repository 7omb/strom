"""`strom_tools.commands.baseline` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import baseline, command_line

if __name__ == "__main__":
    sys.exit(command_line.run(baseline.main))
