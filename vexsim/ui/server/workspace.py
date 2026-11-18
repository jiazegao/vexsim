"""Endpoints for the server and its folder: /api/info, /api/workspace, /api/files, /api/preview,
/api/configurations."""

from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response

from vexsim.app import configs, files
from vexsim.app.frames import preview_of
from vexsim.app.launch import (
    LAUNCH_FILE,
    LaunchFileError,
    read_configurations,
    write_configurations,
)
from vexsim.app.runspec import RunError, RunSpec
from vexsim.app.workspace import RACY_S
from vexsim.config.field import FieldConfig
from vexsim.ui.protocol import (
    AppInfo,
    Preview,
    PreviewRequest,
    RunConfigurations,
    RunProblem,
    SaveConfigurations,
    WorkspaceFile,
    WorkspaceInfo,
    WorkspaceUnchanged,
)
from vexsim.ui.server.common import run_problem
from vexsim.ui.server.state import UIServer


def _file_mark(path: Path) -> tuple[str, bool]:
    """A file's size and time, in brief, and whether it's been left alone long enough for
    those to stand for what's in it (see ``vexsim.app.workspace.RACY_S``)."""
    try:
        st = path.stat()
    except OSError:
        return "-", True
    return f"{st.st_size}-{st.st_mtime_ns}", st.st_mtime_ns <= time.time_ns() - int(RACY_S * 1e9)


def add_workspace(app: FastAPI, server: UIServer) -> None:
    """Endpoints: the server and its folder, its files, a preview, the saved runs."""

    @app.get("/api/info")
    def info() -> AppInfo:
        return server.info()

    @app.get("/api/workspace")
    def workspace_items(
        unless: str | None = None, fresh: bool = False
    ) -> WorkspaceInfo | WorkspaceUnchanged:
        """What's in the folder. ``unless``: the stamp of the answer the page has; while the
        folder (and its saved runs' file) is as it was then, nothing is read again and the
        answer says so. ``fresh``: read everything, whatever the stamps say."""
        ws = server.workspace
        mark = ws.stamp()
        launch, settled = _file_mark(ws.root / LAUNCH_FILE)
        stamp = f"{mark.digest}.{launch}" if mark.settled and settled else ""
        if stamp and unless == stamp and not fresh:
            return WorkspaceUnchanged(stamp=stamp)
        items = [item.to_dict() for item in ws.scan(fresh)]
        return WorkspaceInfo(root=str(ws.root), name=ws.name, items=items, stamp=stamp)

    def _listed(relative: str) -> tuple[Path, str]:
        """A file the workspace lists (its path and kind), to copy or delete: no other file,
        and not a PROS project's folder."""
        item = next((i for i in server.workspace.scan() if i.path == relative), None)
        if item is None:
            raise ValueError(f"{relative} isn't one of the workspace's files")
        if item.kind == "project":
            raise ValueError(
                f"{relative} is a PROS project's folder: copy or delete it with your file manager"
            )
        return server.workspace.path(relative), item.kind

    @app.post("/api/files/duplicate", responses={422: {}})
    def duplicate_file(request: WorkspaceFile):
        """A copy of a workspace file beside it (a robot's or field's named as a copy)."""
        try:
            path, kind = _listed(request.path)
            made = files.duplicate(path, kind)
        except (configs.PatchError, ValueError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return WorkspaceFile(path=server.workspace.relative(made))

    @app.delete("/api/files", status_code=204, responses={422: {}})
    def delete_file(path: str):
        """A workspace file deleted (one the workspace lists, not a project's folder)."""
        try:
            file, _ = _listed(path)
            file.unlink()
        except (ValueError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return Response(status_code=204)

    @app.post("/api/preview", responses={422: {"model": RunProblem}})
    def preview(request: PreviewRequest):
        """The robot and field before a run: the field view, and drag-to-start."""
        try:
            prepared = server.check(RunSpec(robot=request.robot, field=request.field))
        except RunError as exc:
            return run_problem(exc)
        field = prepared.field or FieldConfig()
        return Preview.model_validate(preview_of(prepared.config, field))

    @app.get("/api/configurations")
    def configurations() -> RunConfigurations:
        try:
            found = read_configurations(server.workspace.root)
        except LaunchFileError as exc:
            return RunConfigurations(file=LAUNCH_FILE, configurations=[], error=str(exc))
        return RunConfigurations(file=LAUNCH_FILE, configurations=found)

    @app.put("/api/configurations", responses={409: {}, 422: {}})
    def save_configurations(request: SaveConfigurations):
        root = server.workspace.root
        try:
            read_configurations(root)
        except LaunchFileError as exc:  # never overwrite a file that may hold someone's work
            return JSONResponse({"detail": f"{exc} (fix the file first)"}, status_code=409)
        try:
            write_configurations(root, request.configurations)
        except LaunchFileError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except OSError as exc:
            return JSONResponse({"detail": f"can't save {LAUNCH_FILE}: {exc}"}, status_code=500)
        return RunConfigurations(file=LAUNCH_FILE, configurations=read_configurations(root))
