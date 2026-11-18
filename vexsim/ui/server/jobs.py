"""Endpoints for long jobs (/api/jobs), what they found (/api/results), a benchmark's scenario and
the saved sweeps."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from vexsim.app import results, runs
from vexsim.app.benchmarks import ScenarioProblem, describe_scenario
from vexsim.app.jsonsafe import dumps
from vexsim.app.launch import LaunchFileError
from vexsim.app.runspec import RunError, RunSpec
from vexsim.app.sweeps import SWEEPS_FILE, SweepError, read_sweeps, write_sweeps
from vexsim.config.field import FieldConfig
from vexsim.ui.protocol import (
    JobInfo,
    ResultAbout,
    ResultReplayRequest,
    RunProblem,
    SaveSweeps,
    ScenarioInfo,
    StartJob,
    SweepsFile,
)
from vexsim.ui.server.common import FILE_TYPES, JSON, run_problem
from vexsim.ui.server.state import UIServer

_JOBS = TypeAdapter(StartJob)


def add_jobs(app: FastAPI, server: UIServer) -> None:
    """Endpoints: long jobs, what they found, a benchmark's scenario, the saved sweeps."""

    @app.post("/api/jobs", responses={422: {}})
    async def start_job(request: Request):
        """Start a job (``StartJob``); 422 with a ``detail`` (and ``issues``) if it can't."""
        try:
            wanted = _JOBS.validate_python(await request.json())
        except ValidationError as exc:
            error = exc.errors()[0]
            where = ".".join(str(part) for part in error["loc"])
            detail = f"{where}: {error['msg']}" if where else error["msg"]
            return JSONResponse({"detail": detail}, status_code=422)
        try:
            job = await run_in_threadpool(server.submit_job, wanted)
        except RunError as exc:
            return run_problem(exc)
        except ScenarioProblem as exc:
            return run_problem(RunError(str(exc), exc.issues))
        except (ValueError, OSError, LaunchFileError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return JobInfo.model_validate(job.to_dict())

    @app.get("/api/jobs")
    def jobs() -> list[JobInfo]:
        return [JobInfo.model_validate(j.to_dict(brief=True)) for j in server.jobs.list()]

    def _job(job_id: str):
        job = server.jobs.get(job_id)
        if job is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"no job {job_id}")
        return job

    @app.get("/api/jobs/{job_id}")
    def job_info(job_id: str, since: int = 0, items_since: int = 0) -> Response:
        job = _job(job_id)
        return Response(dumps(job.to_dict(max(0, since), max(0, items_since))), media_type=JSON)

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str) -> JobInfo:
        job = _job(job_id)
        server.jobs.cancel(job)
        return JobInfo.model_validate(job.to_dict(brief=True))

    # --- what the long jobs found (.vexsim/bench, sweeps, calibrations) ------------------

    def _results_root(kind: str) -> Path:
        if kind not in results.KINDS:
            from fastapi import HTTPException

            raise HTTPException(404, f"no results of kind {kind}")
        return results.results_root(server.workspace.root, kind)

    def _no_result(kind: str, result_id: str) -> JSONResponse:
        return JSONResponse({"detail": f"no {kind} result {result_id}"}, status_code=404)

    @app.get("/api/results/{kind}")
    def list_results(kind: str) -> list[ResultAbout]:
        return [ResultAbout.model_validate(a) for a in results.list_results(_results_root(kind))]

    @app.get("/api/results/{kind}/{result_id}", responses={404: {}})
    def read_result(kind: str, result_id: str) -> Response:
        """A ``BenchResult``, ``SweepResult`` or ``CalibrationResult``."""
        try:
            data = results.read_result(_results_root(kind), result_id)
        except (OSError, ValueError):
            return _no_result(kind, result_id)
        return Response(dumps(data), media_type=JSON)

    @app.delete("/api/results/{kind}/{result_id}", status_code=204, responses={404: {}})
    def delete_result(kind: str, result_id: str) -> Response:
        try:
            results.delete_result(_results_root(kind), result_id)
        except (OSError, ValueError):
            return _no_result(kind, result_id)
        return Response(status_code=204)

    @app.get("/api/results/{kind}/{result_id}/files/{name:path}", responses={404: {}})
    def result_file(kind: str, result_id: str, name: str) -> Response:
        """A file a job wrote: a benchmark's report.html and its charts, CSVs, ..."""
        try:
            path = results.result_file(_results_root(kind), result_id, name)
        except (OSError, ValueError):
            return JSONResponse({"detail": f"no file {name} in {result_id}"}, status_code=404)
        media = FILE_TYPES.get(path.suffix.lower(), "application/octet-stream")
        headers = {"Content-Security-Policy": "sandbox"}  # a report is a page of its own
        if path.suffix.lower() in (".csv", ".yaml"):
            headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
        return FileResponse(path, media_type=media, headers=headers)

    @app.post("/api/results/bench/{result_id}/replay", responses={404: {}, 422: {}})
    def bench_replay(result_id: str, request: ResultReplayRequest) -> Response:
        """A benchmark's worst case on the field, drawn with its scenario's robot and field."""
        store = _results_root("bench")
        try:
            data = results.read_result(store, result_id)
            log = results.result_file(store, result_id, request.file)
        except (OSError, ValueError):
            return JSONResponse({"detail": f"no file {request.file} in {result_id}"}, 404)
        scenario = data["scenario"]
        ws = server.workspace
        inside = ws.root in log.parents
        try:
            prepared = server.check(RunSpec(robot=scenario["robot"], field=scenario["field"]))
            result = runs.replay_of(
                log,
                prepared.config,
                prepared.field or FieldConfig(),
                scenario["robot"],
                ws.relative(log) if inside else str(log),
            )
        except RunError as exc:
            return run_problem(exc)
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        for worst in data.get("worst", []):
            if worst["file"] == request.file:
                result["name"] = (
                    f"{scenario['name']}: the worst of {worst['localizer']} / "
                    f"{worst['controller']} (seed {worst['seed']})"
                )
        return Response(dumps(result), media_type=JSON)

    # --- benchmark scenarios, sweeps, calibration ------------------------------------------

    @app.get("/api/bench/scenario", responses={422: {"model": RunProblem}})
    def scenario_info(path: str):
        """A scenario, described for the Bench page (``ScenarioInfo``)."""
        try:
            info = describe_scenario(server.workspace.path(path), server.workspace.root)
        except ScenarioProblem as exc:
            return run_problem(RunError(str(exc), exc.issues))
        except (OSError, ValueError) as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        return ScenarioInfo.model_validate(info)

    @app.get("/api/sweeps")
    def sweeps() -> SweepsFile:
        try:
            found = read_sweeps(server.workspace.root)
        except SweepError as exc:
            return SweepsFile(file=SWEEPS_FILE, sweeps=[], error=str(exc))
        return SweepsFile(file=SWEEPS_FILE, sweeps=found)

    @app.put("/api/sweeps", responses={409: {}, 422: {}})
    def save_sweeps(request: SaveSweeps):
        root = server.workspace.root
        try:
            read_sweeps(root)
        except SweepError as exc:  # never overwrite a file that may hold someone's work
            return JSONResponse({"detail": f"{exc} (fix the file first)"}, status_code=409)
        try:
            write_sweeps(root, request.sweeps)
        except SweepError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OSError as exc:
            return JSONResponse({"detail": f"can't save {SWEEPS_FILE}: {exc}"}, status_code=500)
        return SweepsFile(file=SWEEPS_FILE, sweeps=read_sweeps(root))
