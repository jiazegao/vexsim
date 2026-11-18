"""Endpoints for recorded runs (/api/runs...), replays, and a real robot's logs."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from vexsim.app import runs
from vexsim.app.jsonsafe import dumps
from vexsim.app.runspec import RunError, RunSpec
from vexsim.config.field import FieldConfig
from vexsim.ui.protocol import ReplayRequest, RunDetails, RunProblem, RunRecord, RunUpdate
from vexsim.ui.server.common import robot_config, run_problem
from vexsim.ui.server.state import UIServer


def add_runs(app: FastAPI, server: UIServer) -> None:
    """Endpoints: recorded runs, replays, and a real robot's logs played back."""

    # --- recorded runs (.vexsim/runs) ------------------------------------------------------

    def _runs_root() -> Path:
        return runs.runs_root(server.workspace.root)

    def _missing(run_id: str) -> JSONResponse:
        return JSONResponse({"detail": f"no run {run_id}"}, status_code=404)

    @app.get("/api/runs")
    def list_runs() -> list[RunRecord]:
        return runs.list_runs(_runs_root())

    @app.get("/api/runs/{run_id}", responses={404: {}})
    def run_details(run_id: str):
        try:
            record = runs.read_record(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return RunDetails(run=record, console=runs.read_console(_runs_root(), run_id))

    @app.patch("/api/runs/{run_id}", responses={404: {}})
    def update_run(run_id: str, update: RunUpdate):
        try:
            return runs.update_record(_runs_root(), run_id, kept=update.kept, name=update.name)
        except (OSError, ValueError):
            return _missing(run_id)

    @app.delete("/api/runs/{run_id}", status_code=204, responses={404: {}})
    def delete_run(run_id: str) -> Response:
        try:
            runs.delete_run(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(status_code=204)

    @app.get("/api/runs/{run_id}/tape", responses={404: {}})
    def run_tape(run_id: str) -> Response:
        """The run to scrub (``Tape``), passed through from its file unchecked: it's big."""
        try:
            tape = runs.read_tape(_runs_root(), run_id)
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(dumps(tape), media_type="application/json")

    @app.get("/api/runs/{run_id}/telemetry", responses={404: {}})
    def run_telemetry(run_id: str) -> Response:
        """The run's telemetry for plots (``Telemetry``)."""
        try:
            columns = runs.telemetry_columns(runs.telemetry_path(_runs_root(), run_id))
        except (OSError, ValueError):
            return _missing(run_id)
        return Response(dumps(columns), media_type="application/json")

    @app.get("/api/runs/{run_id}/telemetry.csv", responses={404: {}})
    def run_csv(run_id: str) -> Response:
        """The 10 ms telemetry log, as ``vexsim run --record`` writes it."""
        import gzip

        try:
            path = runs.telemetry_path(_runs_root(), run_id)
            text = gzip.decompress(path.read_bytes()).decode("utf-8")
        except (OSError, ValueError):
            return _missing(run_id)
        name = f"{run_id}.csv"
        return PlainTextResponse(
            text,
            media_type="text/csv",
            headers={"content-disposition": f'attachment; filename="{name}"'},
        )

    @app.post("/api/replay", responses={422: {"model": RunProblem}})
    def replay(request: ReplayRequest) -> Response:
        """A telemetry log from the workspace as a tape (``Replay``), drawn with a robot."""
        try:
            prepared = server.check(RunSpec(robot=request.robot, field=request.field))
            log = server.workspace.path(request.log)
            result = runs.replay_of(
                log, prepared.config, prepared.field or FieldConfig(), request.robot, request.log
            )
        except RunError as exc:
            return run_problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return Response(dumps(result), media_type="application/json")

    @app.get("/api/mcllog", responses={422: {"model": RunProblem}})
    def mcl_log(path: str) -> Response:
        """An MCL log from the workspace, to play on the field (``MclLogTape``)."""
        from vexsim.mcllog import MclLogError

        try:
            tape = runs.mcl_tape(server.workspace.path(path), path)
        except (MclLogError, ValueError) as exc:
            return JSONResponse(RunProblem(error=f"{path}: {exc}", issues=[]).model_dump(), 422)
        return Response(dumps(tape), media_type="application/json")

    @app.get("/api/robotlog", responses={422: {"model": RunProblem}})
    def robot_log(path: str, robot: str | None = None) -> Response:
        """A robot log from the workspace, to play on the field (``RobotLogTape``): its rays
        drawn from where ``robot`` (a robot config) mounts the distance sensors. A log with no
        path to play answers why (``NothingToPlay``): it isn't an error, but a log for a fit."""
        from vexsim.app.logtape import LogTapeError, NothingToPlay, robot_log_tape

        try:
            config = robot_config(server, robot) if robot else None
            tape = robot_log_tape(server.workspace.path(path), path, config)
        except RunError as exc:
            return run_problem(exc)
        except NothingToPlay as exc:
            return JSONResponse({"kind": "none", "path": path, "why": str(exc)})
        except (LogTapeError, ValueError) as exc:
            return JSONResponse(RunProblem(error=f"{path}: {exc}", issues=[]).model_dump(), 422)
        return Response(dumps(tape), media_type="application/json")
