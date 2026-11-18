"""Endpoints for live runs: /api/sessions and each one's WebSocket, and /api/presence."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from pydantic import TypeAdapter, ValidationError
from starlette.concurrency import run_in_threadpool

from vexsim.app.jsonsafe import dumps
from vexsim.app.runspec import RunError
from vexsim.app.session import Session
from vexsim.ui.protocol import ClientCommand, RunProblem, SessionInfo, StartSession
from vexsim.ui.server.common import run_problem
from vexsim.ui.server.state import UIServer

_COMMANDS = TypeAdapter(ClientCommand)


def add_sessions(app: FastAPI, server: UIServer) -> None:
    """Endpoints: live runs, each one's WebSocket, and the pages' presence."""

    @app.post("/api/sessions", responses={422: {"model": RunProblem}})
    def start_session(request: StartSession):
        try:
            session = server.start_session(request)
        except RunError as exc:
            return run_problem(exc)
        return SessionInfo.model_validate(session.info())

    @app.post("/api/sessions/{session_id}/restart", responses={422: {"model": RunProblem}})
    def restart_session(session_id: str):
        """The session's run again, with its code as it is now: the session that runs it
        (itself, if none of its files has changed since it started)."""
        session = server.sessions.get(session_id)
        if session is None:
            return JSONResponse({"detail": f"no session {session_id}"}, status_code=404)
        try:
            session = server.restart_session(session)
        except RunError as exc:
            return run_problem(exc)
        return SessionInfo.model_validate(session.info())

    @app.get("/api/sessions")
    def sessions() -> list[SessionInfo]:
        return [SessionInfo.model_validate(s.info()) for s in server.sessions.values()]

    def _session(session_id: str) -> Session:
        session = server.sessions.get(session_id)
        if session is None:
            from fastapi import HTTPException

            raise HTTPException(404, f"no session {session_id}")
        return session

    @app.get("/api/sessions/{session_id}")
    def session_info(session_id: str) -> SessionInfo:
        return SessionInfo.model_validate(_session(session_id).info())

    @app.delete("/api/sessions/{session_id}", status_code=204)
    def stop_session(session_id: str) -> Response:
        server.stop_session(_session(session_id))
        return Response(status_code=204)

    @app.websocket("/api/presence")
    async def presence(websocket: WebSocket):
        """Held open by each of the app's pages while it's open."""
        server.pages.opened()  # before the page hears it's connected
        try:
            await websocket.accept()
            while True:
                await websocket.receive_text()  # the page says nothing; this ends when it goes
        except WebSocketDisconnect:
            pass
        finally:
            server.pages.closed()

    @app.websocket("/api/sessions/{session_id}/ws")
    async def session_socket(websocket: WebSocket, session_id: str):
        session = server.sessions.get(session_id)
        if session is None:
            await websocket.close(code=4404, reason=f"no session {session_id}")
            return
        await websocket.accept()
        channel = f"session:{session_id}"
        subscriber = server.hub.subscribe(channel)
        catch_up, subscriber.floor = session.catch_up()
        for message in catch_up:
            subscriber.push(message)

        async def send_messages():
            while True:
                await websocket.send_text(dumps(await subscriber.next()))

        sender = asyncio.create_task(send_messages())
        try:
            while True:
                data = await websocket.receive_json()
                try:
                    command = _COMMANDS.validate_python(data)
                except ValidationError as exc:
                    problem = {"type": "error", "message": f"bad command: {exc.errors()[0]['msg']}"}
                    subscriber.push({**problem, "issues": [], "traceback": None})
                    continue
                await run_in_threadpool(session.command, command.model_dump())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            sender.cancel()
            server.hub.unsubscribe(channel, subscriber)
