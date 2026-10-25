"""Validation results shared by all config loaders."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Literal, TypeVar

Severity = Literal["error", "warning"]
T = TypeVar("T")


@dataclass(frozen=True)
class ConfigIssue:
    severity: Severity
    location: str  # dotted path into the document, e.g. "drivetrain.wheels[2].diameter_in"
    message: str

    def __str__(self) -> str:
        where = self.location or "(document)"
        return f"{self.severity}: {where}: {self.message}"


class ConfigError(Exception):
    """Raised when a config has one or more errors."""

    def __init__(self, source: str, issues: list[ConfigIssue]):
        self.source = source
        self.issues = issues
        super().__init__(str(self))

    def __str__(self) -> str:
        errors = [i for i in self.issues if i.severity == "error"]
        lines = [f"{self.source}: {len(errors)} error(s)"]
        lines += [f"  {issue}" for issue in errors]
        return "\n".join(lines)


@dataclass
class ValidationReport(Generic[T]):
    """Outcome of validating one config document.

    ``config`` is None when the document could not be parsed into the schema.
    It is set (and may still have semantic errors) when parsing succeeded.
    """

    source: str
    config: T | None
    issues: list[ConfigIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ConfigIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> T:
        if not self.ok or self.config is None:
            raise ConfigError(self.source, self.issues)
        return self.config
