"""The server and its folder: what's in it, the saved runs, a preview of a robot on its field, a
file made in it, and vexsim's own documents."""

from __future__ import annotations

from typing import Literal

from vexsim.app.launch import RunConfiguration
from vexsim.ui.protocol.base import ItemKind, _Message
from vexsim.ui.protocol.scene import FieldScene, RobotScene


class AppInfo(_Message):
    version: str
    workspace: str  # the workspace folder
    workspace_name: str
    python: str
    platform: str
    pages: int  # the app's pages open on this server now


class WorkspaceItem(_Message):
    kind: ItemKind
    path: str  # relative to the workspace, with / separators
    name: str
    detail: str
    problem: str  # why it won't work as it is; empty if it will


class WorkspaceInfo(_Message):
    root: str
    name: str
    items: list[WorkspaceItem]
    # a mark of the folder as this answer found it, to ask again with (``?unless=``); empty
    # while a file in it is being written
    stamp: str = ""


class WorkspaceUnchanged(_Message):
    """``GET /api/workspace?unless=stamp``: the folder is as it was when that stamp was
    given, so the answer the page has still stands (nothing was read to say so)."""

    unchanged: Literal[True] = True
    stamp: str


class PreviewRequest(_Message):
    robot: str  # workspace paths
    field: str | None = None


class Preview(_Message):
    """A robot and a field before any run, to show them and drag the robot to its start."""

    robot: RobotScene
    field: FieldScene
    pieces: list[tuple[float, float]]  # where the field config puts the pieces


class RunConfigurations(_Message):
    file: str  # workspace path of the file they're kept in
    configurations: list[RunConfiguration]
    error: str | None = None  # why the file couldn't be read (it is then left alone)


class SaveConfigurations(_Message):
    configurations: list[RunConfiguration]


class GuideDocument(_Message):
    """One of vexsim's own documents (the README, a file in docs/), for the Guide page."""

    id: str
    path: str  # from the repository's top: README.md, docs/cpp.md
    title: str
    about: str  # what it's for, in a few words


class GuideIndex(_Message):
    """``GET /api/guide``: the documents there are to read. ``available``: they're installed
    beside vexsim, so the page can show them; otherwise it links to ``repository``'s."""

    available: bool
    repository: str
    documents: list[GuideDocument]


class GuideText(_Message):
    """``GET /api/guide/doc?id=``: a document's Markdown."""

    document: GuideDocument
    text: str


class WorkspaceFile(_Message):
    """A file in the workspace, by its path there: one to copy (``POST /api/files/duplicate``,
    which answers with the copy's), or the copy."""

    path: str
