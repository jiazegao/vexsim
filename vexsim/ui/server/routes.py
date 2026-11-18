"""Endpoints for the autonomous maker (/api/route...), and a PROS project's routines."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from vexsim.app import configs, yamledit
from vexsim.ui.protocol import (
    ExportedFile,
    ExportedRoutine,
    MirroredRoute,
    MirrorRouteRequest,
    NewRoute,
    NewRouteRequest,
    NotRoutineInfo,
    ProjectRoutines,
    RouteCheckRequest,
    RouteFile,
    RouteInfo,
    RoutePatched,
    RoutePatchRequest,
    RoutesExport,
    RoutesExportRequest,
    RoutineInfo,
    RunProblem,
)
from vexsim.ui.server.checks import _route_checked
from vexsim.ui.server.common import config_file
from vexsim.ui.server.state import UIServer


def add_routes(app: FastAPI, server: UIServer) -> None:
    """Endpoints: routes in the maker: opened, checked, patched, new, mirrored, exported."""

    def _route_file(relative: str) -> Path:
        path = config_file(server, relative)
        from vexsim.app.routes import project_of

        if project_of(path) is None:
            raise ValueError(f"{relative} isn't in a PROS project's routes/ folder")
        return path

    @app.get("/api/route", responses={400: {}, 404: {}, 422: {}})
    def open_route(path: str):
        """A route to edit (``RouteFile``), checked."""
        try:
            file = _route_file(path)
            read = configs.read_config(file)
        except FileNotFoundError:
            return JSONResponse({"detail": f"{path} doesn't exist"}, status_code=404)
        except UnicodeDecodeError:
            return JSONResponse({"detail": f"{path} isn't UTF-8 text"}, status_code=422)
        except (OSError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return RouteFile(
            path=server.workspace.relative(file),
            text=read.text,
            version=read.version,
            check=_route_checked(server.workspace, file, read.text),
        )

    @app.post("/api/route/check", responses={400: {}})
    def check_route(request: RouteCheckRequest):
        """A route's text as it's being edited, checked."""
        try:
            file = _route_file(request.path)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        return _route_checked(server.workspace, file, request.text)

    @app.post("/api/route/patch", responses={400: {}, 422: {}})
    def patch_route(request: RoutePatchRequest):
        """A route's text changed in place (a value set, a step added, inserted, moved or
        removed), everything else in it, comments and all, as it was."""
        try:
            file = _route_file(request.path)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        changes = [yamledit.Change(e.op, e.location, e.value) for e in request.edits]
        try:
            text = yamledit.apply(request.text, changes)
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return RoutePatched(text=text, check=_route_checked(server.workspace, file, text))

    @app.post("/api/routes/new", responses={422: {}})
    def new_route(request: NewRouteRequest):
        """A new route in a PROS project's routes/ folder, with no steps (never over a
        file): its robot and field relative to it, its start as LemLib has it."""
        from vexsim.app import routes
        from vexsim.bridge.build import is_pros_project

        ws = server.workspace
        try:
            project = ws.path(request.project)
            if not is_pros_project(project):
                raise ValueError(f"{request.project} isn't a PROS project")
            folder = project / routes.FOLDER
            name = request.name.strip() or "New route"
            file = folder / routes.route_file_name(name)
            stem, count = file.stem, 2
            while file.exists():
                file, count = folder / f"{stem}_{count}.yaml", count + 1
            relative = {
                key: Path(os.path.relpath(ws.path(value), folder)).as_posix() if value else None
                for key, value in (("robot", request.robot), ("field", request.field))
            }
            x, y, heading = request.start
            start = (x, y, (90.0 - heading) % 360.0)  # LemLib's theta
            text = routes.new_route_text(name, relative["robot"], relative["field"], start)
            folder.mkdir(exist_ok=True)
            with open(file, "x", encoding="utf-8", newline="\n") as out:
                out.write(text)
        except (ValueError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return NewRoute(path=ws.relative(file))

    @app.post("/api/routes/mirror", responses={400: {}, 422: {}})
    def mirror_route(request: MirrorRouteRequest):
        """A copy of a route beside it, mirrored for the other side of the field (never over
        a file): its path, and what couldn't be mirrored."""
        from vexsim.app import routes

        try:
            file = _route_file(request.path)
            text, notes = routes.mirror_text(request.text, file, request.axis)
            made, count = file.with_name(f"{file.stem}_mirrored.yaml"), 2
            while made.exists():
                made, count = file.with_name(f"{file.stem}_mirrored_{count}.yaml"), count + 1
            with open(made, "x", encoding="utf-8", newline="") as out:
                out.write(text)
        except (ValueError, OSError, configs.PatchError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return MirroredRoute(path=server.workspace.relative(made), notes=notes)

    def _routes_export(project: str, write: bool) -> RoutesExport | JSONResponse:
        from vexsim.app import autons

        ws = server.workspace
        try:
            folder = ws.path(project)
            done = (autons.export if write else autons.plan_export)(folder)
        except (ValueError, OSError) as exc:  # ExportError is a ValueError
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return RoutesExport(
            project=ws.relative(folder),
            routines=[
                ExportedRoutine(name=r.name, route=r.route, start=r.start) for r in done.routines
            ],
            files=[ExportedFile(path=f.path, state=f.state, diff=f.diff()) for f in done.files],
            left_out=done.left_out,
            notes=done.notes,
        )

    @app.get("/api/routes/export", responses={422: {}})
    def plan_routes_export(project: str):
        """What exporting a project's routes would write (``RoutesExport``), written nowhere."""
        return _routes_export(project, write=False)

    @app.post("/api/routes/export", responses={422: {}})
    def routes_export(request: RoutesExportRequest):
        """A project's routes written into it as routines: only the files that change."""
        return _routes_export(request.project, write=True)


def add_routines(app: FastAPI, server: UIServer) -> None:
    """Endpoints: a PROS project's routines and routes."""

    @app.get("/api/routines", responses={422: {"model": RunProblem}})
    def project_routines(project: str) -> Response:
        """A PROS project's autonomous routines (``ProjectRoutines``), to pick one to run."""
        from vexsim.bridge.build import is_pros_project
        from vexsim.bridge.routines import AUTON_HEADER, find_routines

        try:
            folder = server.workspace.path(project)
        except ValueError as exc:
            return JSONResponse(RunProblem(error=str(exc), issues=[]).model_dump(), 422)
        folder = folder.parent if folder.is_file() else folder  # project.pros, say
        if not is_pros_project(folder):
            problem = RunProblem(error=f"{project} isn't a PROS project", issues=[])
            return JSONResponse(problem.model_dump(), 422)
        found = find_routines(folder)
        listed = ProjectRoutines(
            header=AUTON_HEADER,
            found=found is not None,
            routines=[
                RoutineInfo(name=r.name, line=r.line, source=r.source, start=r.start_pose())
                for r in (found.routines if found else [])
            ],
            others=[
                NotRoutineInfo(name=o.name, line=o.line, why=o.why)
                for o in (found.others if found else [])
            ],
            routes=_routes(folder),
        )
        unused = {"routes"} if not listed.routes else set()  # a project without routes: as before
        return Response(listed.model_dump_json(exclude=unused), media_type="application/json")

    def _routes(project: Path) -> list[RouteInfo]:
        """The project's routes, as a run takes them."""
        from vexsim.app.runspec import route_defaults

        ws = server.workspace
        listed = []
        for item in ws.scan_routes(project):
            given = route_defaults(item.path, ws.root)
            listed.append(
                RouteInfo(
                    path=item.path,
                    name=item.name,
                    robot=given.get("robot"),
                    field=given.get("field"),
                    start=given.get("start"),
                    problem=item.problem or None,
                )  # fmt: skip
            )
        return listed
