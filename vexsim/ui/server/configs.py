"""Endpoints for the config editors (/api/config...), and for what the app makes new: a robot,
a first program, a drive from a preset."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from vexsim.app import configs, newrobot, starter, yamledit
from vexsim.ui.protocol import (
    ConfigCheck,
    ConfigCheckRequest,
    ConfigDriveRequest,
    ConfigFile,
    ConfigOverridesRequest,
    ConfigPatched,
    ConfigPatchRequest,
    ConfigSave,
    ConfigSaved,
    NewRobot,
    NewRobotRequest,
    WorkspaceFile,
)
from vexsim.ui.server.checks import _checked
from vexsim.ui.server.common import config_file
from vexsim.ui.server.state import UIServer


def add_configs(app: FastAPI, server: UIServer) -> None:
    """Endpoints: configs in their editors: opened, checked, patched, saved."""

    @app.get("/api/config", responses={400: {}, 404: {}, 422: {}})
    def open_config(path: str):
        """A robot or field config to edit (``ConfigFile``), checked."""
        try:
            file = config_file(server, path)
            read = configs.read_config(file)
        except FileNotFoundError:
            return JSONResponse({"detail": f"{path} doesn't exist"}, status_code=404)
        except UnicodeDecodeError:
            return JSONResponse({"detail": f"{path} isn't UTF-8 text"}, status_code=422)
        except (OSError, ValueError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        kind = configs.kind_of(read.text)
        if kind is None:
            detail = f"{path} isn't a robot or field config"
            return JSONResponse({"detail": detail}, status_code=422)
        return ConfigFile(
            path=server.workspace.relative(file),
            kind=kind,
            text=read.text,
            version=read.version,
            check=_checked(configs.check_text(read.text, kind)),
        )

    @app.post("/api/config/check")
    def check_config(request: ConfigCheckRequest) -> ConfigCheck:
        """A config's text as it's being typed, checked."""
        return _checked(configs.check_text(request.text, request.kind))

    @app.post("/api/config/patch", responses={422: {}})
    def patch_config(request: ConfigPatchRequest):
        """A config's text changed in place: numbers a drag on the editor's diagram moved,
        and the Design view's changes (a value set, a list item added or removed, a key
        renamed), everything else in it as it was."""
        edits = [
            configs.Edit(e.location, e.value)
            if e.op is None
            else yamledit.Change(e.op, e.location, e.value)
            for e in request.edits
        ]
        try:
            text = yamledit.apply(request.text, edits)
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return ConfigPatched(text=text, check=_checked(configs.check_text(text, request.kind)))

    @app.post("/api/config/overrides", responses={422: {}})
    def config_overrides(request: ConfigOverridesRequest):
        """Fitted values set under a robot config's ``overrides``, in its text."""
        try:
            text = configs.set_overrides(request.text, request.values)
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return ConfigPatched(text=text, check=_checked(configs.check_text(text, "robot")))

    @app.put("/api/config", responses={400: {}, 404: {}, 409: {}})
    def save_config(request: ConfigSave):
        """Write a config, in its own line endings; refused (409, with the version on disk)
        if it changed since it was opened."""
        try:
            file = config_file(server, request.path)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=400)
        with server.saving:
            try:
                current = configs.read_config(file)
            except FileNotFoundError:
                detail = f"{request.path} doesn't exist any more"
                return JSONResponse({"detail": detail}, status_code=404)
            except (OSError, UnicodeDecodeError) as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            if request.version is not None and request.version != current.version:
                detail = f"{request.path} changed on disk since you opened it"
                return JSONResponse({"detail": detail, "version": current.version}, status_code=409)
            try:
                version = configs.write_config(file, request.text, current)
            except OSError as exc:
                return JSONResponse(
                    {"detail": f"can't save {request.path}: {exc}"}, status_code=500
                )
        return ConfigSaved(version=version)


def add_new(app: FastAPI, server: UIServer) -> None:
    """Endpoints: what the app makes: a robot, a first program, a drive from a preset."""

    @app.post("/api/config/new", responses={422: {}})
    def new_robot(request: NewRobotRequest):
        """A new robot config in the workspace (never over a file): to draw, on a drive
        preset, or a copy of a robot."""
        try:
            file = config_file(server, request.path)
            copy = None if request.source is None else config_file(server, request.source)
            newrobot.create(file, request.name.strip() or "New robot", request.preset, copy)
        except (configs.PatchError, ValueError, OSError) as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return NewRobot(path=server.workspace.relative(file))

    @app.post("/api/programs/starter", responses={422: {}})
    def starter_program():
        """A first program written into the workspace's programs/ folder (never over a
        file): a short autonomous routine and a tank drive, to run, read and change."""
        try:
            file = starter.write_starter(server.workspace.root)
        except OSError as exc:
            return JSONResponse({"detail": f"can't write the program: {exc}"}, status_code=422)
        return WorkspaceFile(path=server.workspace.relative(file))

    @app.post("/api/config/drive", responses={422: {}})
    def config_drive(request: ConfigDriveRequest):
        """A drivetrain preset put on a robot config's text, the rest of it as it was."""
        try:
            text = yamledit.apply(
                request.text, newrobot.preset_changes(request.text, request.preset)
            )
        except configs.PatchError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return ConfigPatched(text=text, check=_checked(configs.check_text(text, "robot")))
