"""Robot and field configuration: schemas, YAML loading, validation."""

from vexsim.config.field import FieldConfig
from vexsim.config.issues import ConfigError, ConfigIssue, ValidationReport
from vexsim.config.loader import load_field, load_robot, validate_field, validate_robot
from vexsim.config.robot import RobotConfig

__all__ = [
    "ConfigError",
    "ConfigIssue",
    "FieldConfig",
    "RobotConfig",
    "ValidationReport",
    "load_field",
    "load_robot",
    "validate_field",
    "validate_robot",
]
