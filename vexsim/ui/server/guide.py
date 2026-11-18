"""Endpoints for the workspace's pictures (/api/image) and vexsim's own documents
(/api/guide...)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

from vexsim.app import guide
from vexsim.ui.protocol import GuideDocument, GuideIndex, GuideText
from vexsim.ui.server.state import UIServer


def add_guide(app: FastAPI, server: UIServer) -> None:
    """Endpoints: the workspace's pictures, and vexsim's own documents."""

    @app.get("/api/image", responses={404: {}})
    def workspace_image(path: str) -> Response:
        """A picture in the workspace: a calibration plan's map, a session's report's plots."""
        try:
            file = server.workspace.path(path)
        except ValueError:
            file = None
        if file is None or file.suffix.lower() != ".png" or not file.is_file():
            return JSONResponse({"detail": f"no picture {path}"}, status_code=404)
        return FileResponse(file, media_type="image/png", headers={"Cache-Control": "no-cache"})

    # --- vexsim's own documents, for the Guide page ------------------------------------------

    def _guide_document(document: guide.Document) -> GuideDocument:
        return GuideDocument(
            id=document.id, path=document.path, title=document.title, about=document.about
        )

    @app.get("/api/guide")
    def guide_index() -> GuideIndex:
        """The documents there are to read; where they aren't installed, every one vexsim
        has, for the page to link to in the repository."""
        found = guide.documents()
        if found:
            documents = [_guide_document(d) for d in found]
            return GuideIndex(available=True, repository=guide.REPOSITORY, documents=documents)
        elsewhere = [
            GuideDocument(id=name, path=path, title=Path(path).name, about=about)
            for name, path, about in guide.listed()
        ]
        return GuideIndex(available=False, repository=guide.REPOSITORY, documents=elsewhere)

    @app.get("/api/guide/doc", responses={404: {}})
    def guide_document(id: str):
        try:
            document, text = guide.read(id)
        except (KeyError, OSError):
            return JSONResponse({"detail": f"no document {id}"}, status_code=404)
        return GuideText(document=_guide_document(document), text=text)

    @app.get("/api/guide/file", responses={404: {}})
    def guide_file(path: str) -> Response:
        """A picture one of the documents shows."""
        try:
            file = guide.picture(path)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=404)
        return FileResponse(file, headers={"Cache-Control": "max-age=300"})
