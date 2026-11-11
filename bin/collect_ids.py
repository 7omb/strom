"""`strom_tools.commands.collect_ids` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import collect_ids, command_line  # noqa: E402

if __name__ == "__main__":
    sys.exit(command_line.run(collect_ids.main))
