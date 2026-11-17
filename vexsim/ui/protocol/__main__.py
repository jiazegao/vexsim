"""``python -m vexsim.ui.protocol frontend/src/protocol.ts`` writes the page's types (with no
file: prints them)."""

import sys
from pathlib import Path

from vexsim.ui.protocol.typescript import typescript

if __name__ == "__main__":
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(typescript(), encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(typescript())
