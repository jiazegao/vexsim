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
