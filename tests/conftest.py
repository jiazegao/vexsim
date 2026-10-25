import copy
from pathlib import Path

import pytest

from vexsim.config.yaml_io import load_yaml_file

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_ROBOT = ROOT / "examples" / "robots" / "full_omni_6m.yaml"
EXAMPLE_FIELD = ROOT / "examples" / "fields" / "v5rc_empty.yaml"

_EXAMPLE_DATA = load_yaml_file(EXAMPLE_ROBOT)


@pytest.fixture
def robot_data():
    """A fresh, mutable copy of the example robot as plain data."""
    return copy.deepcopy(_EXAMPLE_DATA)
