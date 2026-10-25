import csv
import io

import pytest

from vexsim.cli import main


def test_csv_output(capsys):
    assert main(["motor-curves", "--cartridge", "blue", "--points", "5", "--csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(capsys.readouterr().out)))
    assert len(rows) == 10
    velocity = [r for r in rows if r["command"] == "velocity"]
    assert float(velocity[0]["speed_rpm"]) == 0.0
    assert float(velocity[-1]["speed_rpm"]) == pytest.approx(600.0)
    assert float(velocity[0]["current_a"]) == pytest.approx(2.5)


def test_png_output(tmp_path, capsys):
    pytest.importorskip("matplotlib")
    out = tmp_path / "curves.png"
    assert main(["motor-curves", "--points", "9", "--out", str(out)]) == 0
    assert out.stat().st_size > 10_000
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_drift_command(capsys, tmp_path):
    from tests.conftest import EXAMPLE_ROBOT

    args = ["drift", str(EXAMPLE_ROBOT), "--seconds", "0.5", "--lateral-mu", "0.4,0.1", "--csv"]
    assert main(args) == 0
    out = capsys.readouterr().out
    errors = [float(line.split("off by ")[1].split()[0]) for line in out.splitlines()[:2]]
    assert errors[1] > errors[0] > 0  # less roller friction, more drift
    assert "lateral_mu,sample,true_x_in" in out


def test_drift_rejects_bad_input(capsys, tmp_path):
    from tests.conftest import EXAMPLE_ROBOT

    assert main(["drift", str(EXAMPLE_ROBOT), "--lateral-mu", "lots"]) == 1
    assert main(["drift", str(tmp_path / "missing.yaml")]) == 1
