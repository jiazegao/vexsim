"""What the endpoints share: where the built page is, the kinds of the files served, how a run
that can't start is told, a config of the workspace found and loaded."""

from __future__ import annotations

from pathlib import Path

from fastapi.responses import JSONResponse

from vexsim.app.runspec import RunError, RunSpec
from vexsim.config.robot import RobotConfig
from vexsim.ui.protocol import RunProblem
from vexsim.ui.server.state import UIServer

STATIC = Path(__file__).parent.parent / "static"
JSON = "application/json"
FILE_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".csv": "text/csv; charset=utf-8",
    ".yaml": "text/yaml; charset=utf-8",
    ".json": JSON,
}


def run_problem(exc: RunError) -> JSONResponse:
    """Why a run can't start, as the page is told: 422 with a ``RunProblem``."""
    issues = [
        {"severity": i.severity, "location": i.location, "message": i.message} for i in exc.issues
    ]
    problem = RunProblem(error=exc.message, issues=issues)
    return JSONResponse(problem.model_dump(), status_code=422)


def config_file(server: UIServer, relative: str) -> Path:
    """A YAML file of the workspace, by its path there (raises ValueError for any other)."""
    path = server.workspace.path(relative)
    if path.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError(f"{relative} isn't a YAML file")
    return path


def robot_config(server: UIServer, path: str) -> RobotConfig:
    """A robot config of the workspace, loaded and checked."""
    prepared = server.check(RunSpec(robot=path))  # raises RunError
    return prepared.config
