"""Shared test data, plus fixtures for the C++ bridge tests (test_bridge.py, test_lemlib.py).

The C++ tests compile with g++. Without a compiler they are skipped, unless
VEXSIM_REQUIRE_CXX is set (as in CI), which turns the skip into a failure.
"""

import copy
import os
from contextlib import contextmanager
from pathlib import Path

import pytest

from vexsim.bridge.build import BuildError, build_project, find_toolchain
from vexsim.config.yaml_io import load_yaml_file

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_ROBOT = ROOT / "examples" / "robots" / "full_omni_6m.yaml"
EXAMPLE_FIELD = ROOT / "examples" / "fields" / "v5rc_empty.yaml"

_EXAMPLE_DATA = load_yaml_file(EXAMPLE_ROBOT)


@pytest.fixture
def robot_data():
    """A fresh, mutable copy of the example robot as plain data."""
    return copy.deepcopy(_EXAMPLE_DATA)


@contextmanager
def using_cache(path: Path):
    old = os.environ.get("VEXSIM_CACHE_DIR")
    os.environ["VEXSIM_CACHE_DIR"] = str(path)
    try:
        yield
    finally:
        if old is None:
            del os.environ["VEXSIM_CACHE_DIR"]
        else:
            os.environ["VEXSIM_CACHE_DIR"] = old


@pytest.fixture(scope="session")
def cache_dir(tmp_path_factory):
    """One build cache for the session, so vexsim's runtime and LemLib compile once."""
    try:
        toolchain = find_toolchain()
        problems = toolchain.problems()
        if problems:
            raise BuildError("; ".join(problems))
    except BuildError as exc:
        if os.environ.get("VEXSIM_REQUIRE_CXX"):
            raise
        pytest.skip(f"no usable C++ compiler: {exc}")
    return tmp_path_factory.mktemp("vexsim-build-cache")


@pytest.fixture(scope="session")
def in_cache(cache_dir):
    """in_cache() -> a context manager that points vexsim at the session's build cache."""
    return lambda: using_cache(cache_dir)


@pytest.fixture(scope="session")
def build(cache_dir):
    """build(project, **kwargs) -> BuildResult, in the session's cache."""

    def _build(project: Path, **kwargs):
        with using_cache(cache_dir):
            return build_project(project, **kwargs)

    return _build


@pytest.fixture(scope="session")
def lemlib_build(build):
    """build(project) for projects that use LemLib (fetched and compiled on first use);
    skips when LemLib can't be downloaded, unless VEXSIM_REQUIRE_CXX is set."""

    def _build(project: Path):
        try:
            return build(project)
        except BuildError as exc:
            if "couldn't get LemLib" in str(exc) and not os.environ.get("VEXSIM_REQUIRE_CXX"):
                pytest.skip(str(exc))
            raise

    return _build
