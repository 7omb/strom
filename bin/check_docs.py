"""`strom_tools.commands.check_docs` as a script; its usage: `--help`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from strom_tools.commands import check_docs, command_line

if __name__ == "__main__":
    sys.exit(command_line.run(check_docs.main))
