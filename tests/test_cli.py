import pytest

from tests.conftest import EXAMPLE_FIELD, EXAMPLE_ROBOT
from vexsim.cli import main


def test_validate_example(capsys):
    code = main(["validate-config", str(EXAMPLE_ROBOT), "--field", str(EXAMPLE_FIELD)])
    out = capsys.readouterr().out
    assert code == 0
    assert "Result: OK (0 error(s), 0 warning(s))" in out
    assert "450 rpm" in out and "76.6 in/s" in out
    assert "144.0 x 144.0 in" in out
    out.encode("ascii")  # output must survive any Windows console code page


def test_validate_reports_errors(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text(EXAMPLE_ROBOT.read_text(encoding="utf-8").replace("port: 13", "port: 1"))
    code = main(["validate-config", str(bad)])
    out = capsys.readouterr().out
    assert code == 1
    assert "sensors[3]: port 1 is already used by drivetrain.gearing.left.motors[0]" in out
    assert "Result: INVALID (1 error(s), 0 warning(s))" in out


def test_strict_fails_on_warnings(tmp_path, capsys):
    warn = tmp_path / "warn.yaml"
    warn.write_text(EXAMPLE_ROBOT.read_text(encoding="utf-8").replace("[15, 15]", "[19, 15]"))
    assert main(["validate-config", str(warn), "-q"]) == 0
    assert main(["validate-config", str(warn), "-q", "--strict"]) == 1
    out = capsys.readouterr().out
    assert "body.footprint_in" in out
    assert "name        " not in out  # --quiet hides the summary


def test_missing_file(tmp_path, capsys):
    assert main(["validate-config", str(tmp_path / "nope.yaml")]) == 1
    assert "file not found" in capsys.readouterr().out


def test_version_and_usage(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "vexsim 0.1.0" in capsys.readouterr().out
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2
