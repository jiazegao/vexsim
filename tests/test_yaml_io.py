import pytest

from vexsim.config.issues import ConfigError
from vexsim.config.yaml_io import load_yaml_file, parse_yaml


def test_colon_scalars_stay_strings():
    # Plain YAML 1.1 would turn 36:48 into the base-60 integer 2208.
    data = parse_yaml("a: 36:48\nb: 1:30.5\nc: 12\nd: 0.75\n")
    assert data == {"a": "36:48", "b": "1:30.5", "c": 12, "d": 0.75}


def test_duplicate_key_is_an_error():
    with pytest.raises(Exception, match="duplicate key 'mass_kg'"):
        parse_yaml("mass_kg: 1\nmass_kg: 2\n")


def test_duplicate_nested_key_is_an_error():
    with pytest.raises(Exception, match="duplicate key 'port'"):
        parse_yaml("- {type: imu, port: 1, port: 2}\n")


def test_merge_keys_may_be_overridden():
    data = parse_yaml("base: &b {x: 1, y: 2}\nderived:\n  <<: *b\n  y: 3\n")
    assert data["derived"] == {"x": 1, "y": 3}


def test_file_errors_carry_location(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: 1\nb: [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_yaml_file(path)
    (issue,) = info.value.issues
    assert issue.location.startswith("line ")


def test_duplicate_key_in_file_reports_line(tmp_path):
    path = tmp_path / "dup.yaml"
    path.write_text("a: 1\nb: 2\na: 3\n", encoding="utf-8")
    with pytest.raises(ConfigError) as info:
        load_yaml_file(path)
    (issue,) = info.value.issues
    assert issue.location == "line 3, column 1"
    assert "duplicate key 'a'" in issue.message


def test_missing_and_empty_files(tmp_path):
    with pytest.raises(ConfigError, match="file not found"):
        load_yaml_file(tmp_path / "nope.yaml")
    empty = tmp_path / "empty.yaml"
    empty.write_text("# only a comment\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="file is empty"):
        load_yaml_file(empty)


def test_utf8_is_read_regardless_of_platform_default(tmp_path):
    path = tmp_path / "utf8.yaml"
    path.write_text("name: Équipe 1234Ω  # °\n", encoding="utf-8")
    assert load_yaml_file(path) == {"name": "Équipe 1234Ω"}
