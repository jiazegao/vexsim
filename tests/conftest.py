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


# --- what the server sends, checked (phase 15.6) ------------------------------------------------
#
# Every answer a test gets from the app's server is checked against the model its endpoint is
# said to answer with (vexsim.ui.protocol.RESPONSES), whatever the test itself looks at: an
# endpoint that sends what its model doesn't have, or leaves out what it does, fails the test
# that called it. The server doesn't check as it runs.

_ADAPTERS: dict[int, object] = {}
_ANSWERED: set[tuple[str, str]] = set()  # the endpoints whose answers some test has had checked


def _endpoint(app, method: str, path: str):
    """The app's route that takes a request (its path as declared, the path's values), or
    None: the page and its files, an address nothing answers."""
    from starlette.routing import Match

    scope = {"type": "websocket" if method == "WS" else "http", "path": path, "method": method}
    for route in app.router.routes:
        if not hasattr(route, "endpoint"):
            continue  # the page's files
        match, child = route.matches(scope)
        if match is Match.FULL:
            return route.path, child.get("path_params", {})
    return None


def check_answer(app, method: str, path: str, status: int, body: bytes | str, kind: str) -> None:
    """Fail the test if what an endpoint of the vexsim server answered isn't what
    protocol.RESPONSES says it answers with. ``kind``: the answer's content type."""
    import json

    from pydantic import TypeAdapter, ValidationError

    from vexsim.ui import protocol

    if getattr(getattr(app, "state", None), "server", None) is None:
        return  # not vexsim's server
    found = _endpoint(app, method.upper(), path)
    if found is None:
        return
    route, params = found
    where = f"{method.upper()} {route}"
    if (method.upper(), route) not in protocol.RESPONSES:
        pytest.fail(f"protocol.RESPONSES doesn't say what {where} answers with")
    if method != "WS" and not 200 <= status < 300:
        if "json" in kind:  # an answer that says no says why: a detail, or a RunProblem
            said = json.loads(body)
            if not isinstance(said, dict) or not ("detail" in said or "error" in said):
                pytest.fail(f"{where} said no ({status}) without saying why: {said!r}")
        return
    model = protocol.response_model(method, route, params)
    _ANSWERED.add((method.upper(), route))
    if model is None:
        return
    adapter = _ADAPTERS.get(id(model))
    if adapter is None:
        adapter = _ADAPTERS[id(model)] = TypeAdapter(model)
    try:
        adapter.validate_json(body)
    except ValidationError as exc:
        name = getattr(model, "__name__", str(model))
        pytest.fail(f"{where} answered with what isn't its model ({name}):\n{exc}")


@pytest.fixture(autouse=True, scope="session")
def _answers_checked():
    """Check every answer the tests get from the app's server (see ``check_answer``)."""
    try:
        from starlette.testclient import TestClient, WebSocketTestSession
    except ImportError:  # the app's server isn't installed: its tests skip
        yield
        return
    patch = pytest.MonkeyPatch()
    request, receive = TestClient.request, WebSocketTestSession.receive

    def checked_request(self, method, url, *args, **kwargs):
        response = request(self, method, url, *args, **kwargs)
        kind = response.headers.get("content-type", "")
        path = response.request.url.path
        check_answer(self.app, method, path, response.status_code, response.content, kind)
        return response

    def checked_receive(self):
        message = receive(self)
        if message.get("type") == "websocket.send" and message.get("text") is not None:
            check_answer(self.app, "WS", self.scope["path"], 200, message["text"], "json")
        return message

    patch.setattr(TestClient, "request", checked_request)
    patch.setattr(WebSocketTestSession, "receive", checked_receive)
    yield
    patch.undo()


def pytest_sessionfinish(session, exitstatus):
    """With VEXSIM_REQUIRE_ANSWERS set (CI's run of every test): fail if there's an endpoint
    no test got an answer from, so none goes unchecked. (A page holds /api/presence open and
    is sent nothing, so that one has nothing to check.)"""
    if not os.environ.get("VEXSIM_REQUIRE_ANSWERS") or exitstatus != 0:
        return
    from vexsim.ui import protocol

    missed = sorted(set(protocol.RESPONSES) - _ANSWERED - {("WS", "/api/presence")})
    if missed:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        lines = ["no test got an answer from these endpoints (protocol.RESPONSES):"]
        lines += [f"  {method} {path}" for method, path in missed]
        for line in lines:
            if reporter is not None:
                reporter.write_line(line, red=True)
            else:
                print(line)
        session.exitstatus = 1
