from tests.conftest import EXAMPLE_FIELD
from vexsim.config import FieldConfig, load_field, validate_field


def test_default_field():
    assert load_field() == FieldConfig()
    assert load_field().size_in == (144.0, 144.0)


def test_example_field_file():
    report = validate_field(EXAMPLE_FIELD)
    assert report.ok and report.issues == []
    assert report.config.size_in == (144.0, 144.0)


def test_custom_and_invalid_sizes():
    assert load_field({"size_in": [140.5, 140.5]}).size_in == (140.5, 140.5)
    assert not validate_field({"size_in": [144, 0]}).ok
    assert not validate_field({"size_in": [144, 144], "walls": True}).ok
