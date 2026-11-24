"""``python -m vexsim.physics.compiled``: write step_layout.h from the tables."""

from vexsim.physics.compiled.layout import HEADER, header

HEADER.write_text(header(), encoding="utf-8", newline="\n")
print(f"wrote {HEADER}")
