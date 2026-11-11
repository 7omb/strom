"""The hook command of `.claude/settings.json`: a wrapper of `strom_tools.hooks.dispatcher`."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from strom_tools.hooks import dispatcher  # noqa: E402

if __name__ == "__main__":
    sys.exit(dispatcher.main())
