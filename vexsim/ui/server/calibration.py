"""Endpoints for calibration: a session (/api/calibration/...) and the quick fit
(/api/calibrate/...)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from vexsim.app import configs
from vexsim.app.runspec import RunError, RunSpec
from vexsim.config.field import FieldConfig
from vexsim.ui.protocol import (
    CalibrationProgram,
    CalibrationSessionState,
    CalibrationSetup,
    EndFound,
    EndRequest,
    PassMarks,
    RoutinePlan,
    RoutineRequest,
    RunProblem,
    SavePassMarks,
    SessionApplied,
    SessionApplyRequest,
    SessionCollected,
    SessionCollectRequest,
    SessionUseRequest,
)
from vexsim.ui.server.checks import _checked
from vexsim.ui.server.common import robot_config, run_problem
from vexsim.ui.server.state import UIServer


def add_session(app: FastAPI, server: UIServer) -> None:
    """Endpoints: a calibration session: program, runs, collecting, apply, pass marks."""

    # --- a calibration session (the Calibrate page, vexsim.app.calsession) -----------------

    def _detail(exc: Exception) -> JSONResponse:
        return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)

    def _session_folder(relative: str) -> Path:
        path = server.workspace.path(relative)
        if path == server.workspace.root or path.is_file():
            raise ValueError(f"{relative} isn't a session's folder")
        return path

    def _session_state(relative: str, robot: str | None) -> CalibrationSessionState:
        from vexsim.app.calsession import session_state

        config = robot_config(server, robot) if robot else None
        folder = _session_folder(relative)
        return CalibrationSessionState.model_validate(
            session_state(server.workspace.root, folder, config)
        )

    @app.get("/api/calibration/program", responses={422: {"model": RunProblem}})
    def calibration_program(folder: str):
        """A calibration program's folder: the program, the PROS project, the plan."""
        from vexsim.app.calsession import program_info

        try:
            path = _session_folder(folder)
        except ValueError as exc:
            return _detail(exc)
        return CalibrationProgram.model_validate(program_info(server.workspace.root, path))

    @app.get("/api/calibration/session", responses={422: {"model": RunProblem}})
    def calibration_session(path: str, robot: str | None = None):
        """A calibration session: its runs (each with what it measured, by ``robot``'s config)
        and its latest fit."""
        try:
            return _session_state(path, robot)
        except RunError as exc:
            return run_problem(exc)
        except ValueError as exc:
            return _detail(exc)

    @app.post("/api/calibration/collect", responses={422: {"model": RunProblem}})
    def calibration_collect(request: SessionCollectRequest, robot: str | None = None):
        """The calibration logs on the brain's card (or in a folder), into the session."""
        from vexsim.app.calsession import collect_logs

        try:
            folder = _session_folder(request.session)
            source = Path(request.folder).expanduser() if request.folder else None
            found = collect_logs(folder, source)
            state = _session_state(request.session, robot)
        except RunError as exc:
            return run_problem(exc)
        except (OSError, ValueError) as exc:
            return _detail(exc)
        return SessionCollected(**found, state=state)

    @app.post("/api/calibration/use", responses={422: {"model": RunProblem}})
    def calibration_use(request: SessionUseRequest, robot: str | None = None):
        """Leave a run out of the fit, or put it back."""
        from vexsim.app.calsession import set_use

        try:
            set_use(_session_folder(request.session), request.file, request.use)
            return _session_state(request.session, robot)
        except RunError as exc:
            return run_problem(exc)
        except (OSError, ValueError) as exc:
            return _detail(exc)

    @app.post("/api/calibration/apply", responses={422: {"model": RunProblem}})
    def calibration_apply(request: SessionApplyRequest):
        """A robot config's text with what the session's fit found written in (to look over in
        its editor, and save)."""
        from vexsim.app.calsession import apply_session

        try:
            text, count = apply_session(_session_folder(request.session), request.text)
        except (OSError, ValueError) as exc:
            return _detail(exc)
        checked = configs.check_text(text, "robot")
        return SessionApplied(text=text, check=_checked(checked), changes=count)

    @app.get("/api/calibration/marks")
    def calibration_marks() -> PassMarks:
        """The autonomous check's pass marks: the team's, or vexsim's."""
        from vexsim.app.calsession import pass_marks

        return PassMarks.model_validate(pass_marks(server.workspace.root))

    @app.put("/api/calibration/marks", responses={422: {"model": RunProblem}})
    def save_calibration_marks(request: SavePassMarks):
        """Set the team's pass marks, in the workspace's .vexsim/calibration.yaml."""
        from vexsim.app.calsession import save_marks

        try:
            marks = save_marks(
                server.workspace.root, request.max_distance_in, request.max_heading_deg
            )
        except (OSError, ValueError) as exc:
            return _detail(exc)
        return PassMarks.model_validate(marks)

    @app.post("/api/calibration/end", responses={422: {"model": RunProblem}})
    def calibration_end(request: EndRequest):
        """Where two corners' tape marks put the robot, as the student types them."""
        from vexsim.app.calsession import end_found

        try:
            prepared = server.check(RunSpec(robot=request.robot, field=request.field))
            found = end_found(prepared.config, prepared.field or FieldConfig(), request.text)
        except RunError as exc:
            return run_problem(exc)
        except ValueError as exc:
            return _detail(exc)
        return EndFound.model_validate(found)


def add_quick_fit(app: FastAPI, server: UIServer) -> None:
    """Endpoints: the quick fit: what it can fit, and its routine."""

    @app.get("/api/calibrate/parameters", responses={422: {"model": RunProblem}})
    def calibration_setup(robot: str):
        """The parameters a fit adjusts unless told otherwise, with their values now."""
        from vexsim.app.calibrate import parameters

        try:
            config = robot_config(server, robot)
        except RunError as exc:
            return run_problem(exc)
        return CalibrationSetup(robot=robot, parameters=parameters(config))

    @app.post("/api/calibrate/routine", responses={422: {"model": RunProblem}})
    def calibration_routine(request: RoutineRequest):
        """The calibration routine in a PROS project: what adding it does, or (``write``)
        adding it."""
        from vexsim.app.calibrate import routine_plan, write_routine

        try:
            config = robot_config(server, request.robot)
            project = server.workspace.path(request.project)
            if not (project / "project.pros").is_file() and not (project / "src").is_dir():
                raise ValueError(f"{request.project} isn't a PROS project")
            root = server.workspace.root
            plan = (write_routine if request.write else routine_plan)(config, project, root)
        except RunError as exc:
            return run_problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return RoutinePlan.model_validate(plan)
