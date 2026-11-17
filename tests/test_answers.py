"""What the server sends, checked (phase 15.6): protocol.RESPONSES says what every endpoint
answers with, and the tests' client (conftest.py) checks each answer it gets against it."""

import typing

import pytest

from tests.conftest import ROOT
from tests.test_ui import TOKEN, authorized
from vexsim.ui import protocol

pytest.importorskip("fastapi")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from vexsim.ui.server import create_app

    app = create_app(
        ROOT, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as test_client:
        yield authorized(test_client)


def endpoints(app) -> set[tuple[str, str]]:
    """Every endpoint the server has: (method, path as declared), a WebSocket as "WS"."""
    from fastapi.routing import APIRoute, APIWebSocketRoute

    found = set()
    for route in app.router.routes:
        if isinstance(route, APIRoute):
            found |= {(method, route.path) for method in route.methods}
        elif isinstance(route, APIWebSocketRoute):
            found.add(("WS", route.path))
        else:
            assert type(route).__name__ == "Mount", route  # the page's files, and nothing else
    return found


def test_every_endpoint_says_what_it_answers_with(client):
    served = endpoints(client.app)
    assert served - set(protocol.RESPONSES) == set(), "add them to protocol.RESPONSES"
    assert set(protocol.RESPONSES) - served == set(), "protocol.RESPONSES has endpoints gone"
    assert all(path.startswith("/api/") for _, path in served)
    # and each model it names is one the page's types are written from
    for where, answer in protocol.RESPONSES.items():
        for model in models_in(answer):
            assert model in protocol.MODELS, (where, model)


def models_in(answer):
    """The models an answer is made of: itself, a list's, a union's, each kind's."""
    from pydantic import BaseModel

    if isinstance(answer, dict):
        for one in answer.values():
            yield from models_in(one)
    elif isinstance(answer, type):
        if issubclass(answer, BaseModel):
            yield answer
    else:
        for part in typing.get_args(answer):
            yield from models_in(part)


def test_an_answer_goes_by_the_results_kind():
    path = "/api/results/{kind}/{result_id}"
    assert protocol.response_model("GET", path, {"kind": "bench"}) is protocol.BenchResult
    assert protocol.response_model("get", path, {"kind": "checks"}) is protocol.AutonCheckResult
    assert protocol.response_model("DELETE", path, {"kind": "bench"}) is None
    with pytest.raises(KeyError):
        protocol.response_model("GET", "/api/nothing")


def test_the_tests_client_checks_every_answer(client, monkeypatch):
    assert client.get("/api/info").status_code == 200  # as its model has it
    # an answer that isn't what its endpoint is said to answer with
    monkeypatch.setitem(protocol.RESPONSES, ("GET", "/api/info"), protocol.GuideIndex)
    with pytest.raises(pytest.fail.Exception, match="GET /api/info answered with what isn't"):
        client.get("/api/info")
    # an endpoint nothing is said about
    monkeypatch.delitem(protocol.RESPONSES, ("GET", "/api/info"))
    with pytest.raises(pytest.fail.Exception, match="doesn't say what GET /api/info answers"):
        client.get("/api/info")


def test_the_tests_client_checks_a_runs_messages(client, monkeypatch):
    spec = {"robot": "examples/robots/full_omni_6m.yaml"}
    session = client.post("/api/sessions", json={"spec": spec}).json()
    try:
        with client.websocket_connect(f"/api/sessions/{session['id']}/ws") as socket:
            assert socket.receive_json()["type"] == "session"  # as the protocol has it
            path = ("WS", "/api/sessions/{session_id}/ws")
            monkeypatch.setitem(protocol.RESPONSES, path, protocol.StatusMessage)
            with pytest.raises(pytest.fail.Exception, match="answered with what isn't"):
                while True:  # the first message that isn't a status
                    socket.receive_json()
    finally:
        client.delete(f"/api/sessions/{session['id']}")


def test_a_no_says_why(client):
    said = client.get("/api/config", params={"path": "examples/robots/nothing.yaml"})
    assert said.status_code == 404 and "detail" in said.json()
    from tests.conftest import check_answer

    with pytest.raises(pytest.fail.Exception, match="without saying why"):
        check_answer(client.app, "GET", "/api/config", 404, b'{"oops": 1}', "application/json")
    check_answer(client.app, "GET", "/api/config", 404, b"<html>", "text/html")  # not checked
    check_answer(client.app, "GET", "/assets/nothing.js", 404, b"{}", "application/json")


def test_the_endpoints_only_slow_tests_ask_answer_as_the_protocol_has_them(tmp_path, monkeypatch):
    """A calibration session's endpoints on a card of made-up logs, the going runs, a job
    cancelled: each answer is checked against its model as it comes. (The whole session,
    through the same endpoints, takes minutes: test_calibration_app.py, marked session.)"""
    import json
    import shutil

    from fastapi.testclient import TestClient

    from tests.test_calibration_app import ROBOT, calibration_log
    from vexsim.app import calsession
    from vexsim.ui.server import create_app

    monkeypatch.setenv("VEXSIM_RUNS_DIR", str(tmp_path / "recorded-runs"))
    monkeypatch.setenv("VEXSIM_RESULTS_DIR", str(tmp_path / "results"))
    workspace = tmp_path / "team"
    (workspace / "robots").mkdir(parents=True)
    shutil.copy(ROOT / ROBOT, workspace / "robots")
    robot, session = "robots/1239e_2026-27.yaml", "calibration/2026-11-07"
    card = tmp_path / "card"
    card.mkdir()
    calibration_log(card / "vexsim_0001_push_forward.csv", "push", length_in="96.0", turn=4500)
    calibration_log(card / "vexsim_0002_straight.csv", "straight", spot="0 0 0", turn=1000)
    app = create_app(
        workspace, token=TOKEN, port=8642, hosts={"testserver"}, origins={"http://testserver"}
    )
    with TestClient(app) as client:
        authorized(client)
        collected = client.post(
            "/api/calibration/collect",
            params={"robot": robot},
            json={"session": session, "folder": str(card)},
        )
        assert collected.status_code == 200 and collected.json()["added"] == 2
        state = client.get("/api/calibration/session", params={"path": session, "robot": robot})
        assert [run["test"] for run in state.json()["runs"]] == ["push", "straight"]
        left_out = client.post(
            "/api/calibration/use",
            params={"robot": robot},
            json={"session": session, "file": "vexsim_0002_straight.csv", "use": False},
        )
        assert left_out.status_code == 200 and len(left_out.json()["runs"]) == 2
        # a fit's report, as fitting leaves one: what it found goes into the config's text
        text = (workspace / robot).read_text(encoding="utf-8")
        change = {"location": 'overrides["motor.voltage_cap"]', "value": 1.0, "key": "x"}
        found = {"config_digest": calsession.digest(text), "fitted": "2026-11-07"}
        (workspace / session / "report").mkdir()
        (workspace / session / "report" / "report.json").write_text(
            json.dumps({**found, "changes": [change]}), encoding="utf-8"
        )
        applied = client.post("/api/calibration/apply", json={"session": session, "text": text})
        assert applied.json()["changes"] == 1 and applied.json()["check"]["issues"] == []
        marks = client.put(
            "/api/calibration/marks", json={"max_distance_in": 1.5, "max_heading_deg": 3}
        )
        assert marks.json()["max_distance_in"] == 1.5
        assert client.get("/api/calibration/marks").json() == marks.json()

        # the runs that are going
        assert client.get("/api/sessions").json() == []
        going = client.post("/api/sessions", json={"spec": {"robot": robot}}).json()
        try:
            assert [s["id"] for s in client.get("/api/sessions").json()] == [going["id"]]
        finally:
            client.delete(f"/api/sessions/{going['id']}")
        # a job, cancelled
        job = client.post("/api/jobs", json={"kind": "odometry", "robot": robot}).json()
        cancelled = client.delete(f"/api/jobs/{job['id']}")
        assert cancelled.status_code == 200 and cancelled.json()["id"] == job["id"]
