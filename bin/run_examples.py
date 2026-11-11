"""`strom_tools.commands.run_examples` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import command_line, run_examples  # noqa: E402

if __name__ == "__main__":
    sys.exit(command_line.run(run_examples.main))
