"""What the long jobs found, kept in the workspace: benchmarks in .vexsim/bench/, sweeps in
.vexsim/sweeps/, calibrations in .vexsim/calibrations/, a folder each.

A result's folder holds ``result.json`` (``about``: its id, kind, title, when it was made
and a one-line summary; then whatever its page shows) and the files the job wrote beside
it (a benchmark's report.html, its CSVs, ...). Only the newest ``KEEP`` of each kind stay.
``VEXSIM_RESULTS_DIR`` puts them somewhere else.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path
from typing import Any, Literal

from vexsim.app.jsonsafe import finite

ResultKind = Literal["bench", "sweeps", "calibrations"]
KINDS: tuple[str, ...] = ("bench", "sweeps", "calibrations")
KEEP = 20
STALE_S = 24 * 3600  # a folder still without its result.json after this was abandoned
_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{4}$")
RESULT_FILE = "result.json"


def results_root(workspace: str | os.PathLike[str], kind: str) -> Path:
    """Where a workspace keeps one kind of result."""
    if kind not in KINDS:
        raise ValueError(f"no results of kind {kind!r}")
    elsewhere = os.environ.get("VEXSIM_RESULTS_DIR")
    return (Path(elsewhere) if elsewhere else Path(workspace) / ".vexsim") / kind


def new_result(root: Path) -> tuple[str, Path]:
    """A new result's id and its (new, empty) folder."""
    while True:
        result_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(2)
        folder = root / result_id
        try:
            folder.mkdir(parents=True)
            return result_id, folder
        except FileExistsError:
            continue


def result_dir(root: Path, result_id: str) -> Path:
    """A result's folder; raises ValueError for anything that isn't a result id."""
    if not _ID.match(result_id):
        raise ValueError(f"no result {result_id!r}")
    return root / result_id


def write_result(folder: Path, kind: str, title: str, summary: str, data: dict) -> dict:
    """Save a result (last, once its files are written); returns its ``about``."""
    about = {
        "id": folder.name,
        "kind": kind,
        "title": title,
        "created": time.time(),
        "summary": summary,
    }
    temporary = folder / (RESULT_FILE + ".tmp")
    temporary.write_text(
        json.dumps(finite({"about": about, **data}), separators=(",", ":")), encoding="utf-8"
    )
    temporary.replace(folder / RESULT_FILE)
    return about


def list_results(root: Path) -> list[dict]:
    """Every result's ``about``, newest first (folders that don't read are skipped)."""
    found = []
    if root.is_dir():
        for folder in root.iterdir():
            if not _ID.match(folder.name) or not (folder / RESULT_FILE).is_file():
                continue
            try:
                found.append(read_result(root, folder.name)["about"])
            except (OSError, ValueError, KeyError):
                continue
    return sorted(found, key=lambda about: about["created"], reverse=True)


def read_result(root: Path, result_id: str) -> dict[str, Any]:
    path = result_dir(root, result_id) / RESULT_FILE
    return json.loads(path.read_text(encoding="utf-8"))


def result_file(root: Path, result_id: str, relative: str) -> Path:
    """A file a result's job wrote (raises ValueError outside its folder, FileNotFoundError
    if there's no such file)."""
    folder = result_dir(root, result_id).resolve()
    path = (folder / relative).resolve()
    if folder not in path.parents:
        raise ValueError(f"{relative} isn't in result {result_id}")
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path


def delete_result(root: Path, result_id: str) -> None:
    folder = result_dir(root, result_id)
    if not folder.is_dir():
        raise FileNotFoundError(result_id)
    shutil.rmtree(folder)


def prune(root: Path, keep: int = KEEP) -> list[str]:
    """Delete all but the newest ``keep`` results, and abandoned folders (a job that was
    cancelled or failed partway); returns the ids gone."""
    gone = [about["id"] for about in list_results(root)[keep:]]
    if root.is_dir():
        now = time.time()
        for folder in root.iterdir():
            if (
                _ID.match(folder.name)
                and not (folder / RESULT_FILE).is_file()
                and now - folder.stat().st_mtime > STALE_S
            ):
                gone.append(folder.name)
    for result_id in gone:
        shutil.rmtree(root / result_id, ignore_errors=True)
    return gone
