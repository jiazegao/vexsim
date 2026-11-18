"""Who may talk to the server: its token, its own host, its own pages."""

from __future__ import annotations

import contextlib
import secrets
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, unquote

from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.datastructures import Headers, MutableHeaders

_UNAUTHORIZED = """<!doctype html><meta charset="utf-8"><title>vexsim</title>
<body style="font-family: system-ui, sans-serif; margin: 3em; max-width: 36em">
<h1>This page needs its key</h1>
<p>Open vexsim with the link <code>vexsim ui</code> printed when it started: it ends with
<code>?token=...</code>. If you closed that terminal, run <code>vexsim ui</code> again.</p>
"""


# The app's own scripts, styles and icons: no secrets, and a page inside another app's frame
# (VS Code's panel) loads them without the cookie, which it doesn't get
PUBLIC = ("/assets/", "/icons/")


class Guard:
    """ASGI middleware: the right Host, a valid token (URL, cookie or bearer header) but for
    the app's own files, and, for WebSockets, an Origin of our own. A token in the URL is
    traded for a cookie."""

    def __init__(self, app, *, token: str, cookie: str, hosts: set[str], origins: set[str]):
        self.app = app
        self.token = token
        self.cookie = cookie
        self.hosts = hosts
        self.origins = origins

    def _valid(self, value: str | None) -> bool:
        return bool(value) and secrets.compare_digest(value.encode(), self.token.encode())

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = Headers(scope=scope)
        if headers.get("host", "") not in self.hosts:
            return await self._deny(scope, receive, send, 403, "wrong host")
        if scope["type"] == "http" and scope["path"].startswith(PUBLIC):
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            origin = headers.get("origin")
            if origin is not None and origin not in self.origins:
                return await self._deny(scope, receive, send, 403, "wrong origin")
        raw = scope.get("query_string", b"").decode("latin-1")
        query = parse_qs(raw)
        if "token" not in query:  # a link VS Code opened can come as ?token%3D...
            query = parse_qs(unquote(raw))
        from_url = (query.get("token") or [None])[0]
        cookies = SimpleCookie()
        with contextlib.suppress(Exception):
            cookies.load(headers.get("cookie", ""))
        from_cookie = cookies[self.cookie].value if self.cookie in cookies else None
        bearer = headers.get("authorization", "")
        from_header = bearer[7:] if bearer.lower().startswith("bearer ") else None
        if not any(self._valid(v) for v in (from_cookie, from_header, from_url)):
            return await self._deny(scope, receive, send, 401, "no valid token")
        if scope["type"] == "http" and self._valid(from_url) and not self._valid(from_cookie):
            send = self._setting_cookie(send)
        await self.app(scope, receive, send)

    def _setting_cookie(self, send):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append(
                    "set-cookie",
                    f"{self.cookie}={self.token}; Path=/; HttpOnly; SameSite=Strict",
                )
            await send(message)

        return wrapped

    async def _deny(self, scope, receive, send, status: int, reason: str):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 4000 + status, "reason": reason})
            return
        wants_page = "text/html" in Headers(scope=scope).get("accept", "")
        if wants_page and status == 401:
            response: Response = HTMLResponse(_UNAUTHORIZED, status_code=status)
        else:
            response = JSONResponse({"detail": reason}, status_code=status)
        await response(scope, receive, send)
