"""An isolated X11 browser display, streamed through the WebUI using noVNC."""

from __future__ import annotations

import asyncio
import contextlib
import os
import secrets
import shutil
import socket
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from nicegui import app
from starlette.staticfiles import StaticFiles
from typing_extensions import Self


class BrowserDisplayError(Exception):
    pass


class BrowserDisplay:
    def __init__(self) -> None:
        self._key = ""
        self._port = 0
        self.display = ""
        self._processes: list[asyncio.subprocess.Process] = []
        self._novnc = Path(os.environ.get("WEBUI_NOVNC_PATH", "/usr/share/novnc"))
        app.mount(
            "/browser-login/novnc",
            StaticFiles(directory=self._novnc, check_dir=False),
            name="browser-login-novnc",
        )
        app.get("/browser-login/view/{key}")(self._view)
        app.websocket("/browser-login/socket/{key}")(self._socket)

    @property
    def view_url(self) -> str:
        return f"/browser-login/view/{self._key}" if self._key else ""

    async def __aenter__(self) -> Self:
        if not all(shutil.which(name) for name in ("Xvfb", "x11vnc")):
            raise BrowserDisplayError(
                "Install the Ubuntu packages xvfb, x11vnc and novnc first."
            )
        if not all(
            (self._novnc / name).is_file()
            for name in ("vnc.html", "app/ui.js", "core/rfb.js")
        ):
            raise BrowserDisplayError(
                "noVNC was not found. Install novnc or set WEBUI_NOVNC_PATH."
            )
        try:
            xvfb = await asyncio.create_subprocess_exec(
                "Xvfb",
                "-displayfd",
                "1",
                "-screen",
                "0",
                "1280x900x24",
                "-nolisten",
                "tcp",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._processes.append(xvfb)
            line = await asyncio.wait_for(xvfb.stdout.readline(), timeout=10)
            if not line.strip().isdigit():
                raise BrowserDisplayError("The virtual display could not start.")
            self.display = ":" + line.decode().strip()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                self._port = sock.getsockname()[1]
            vnc = await asyncio.create_subprocess_exec(
                "x11vnc",
                "-display",
                self.display,
                "-rfbport",
                str(self._port),
                "-listen",
                "127.0.0.1",
                "-no6",
                # LibVNCServer's IPv6 listener is separate from x11vnc's -no6.
                "-rfbportv6",
                "-1",
                "-forever",
                "-shared",
                "-nopw",
                "-noxdamage",
                # Xvfb has no display manager; its clipboard can initialize now.
                "-env",
                "X11VNC_AVOID_WINDOWS=never",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._processes.append(vnc)
            for _ in range(50):
                if vnc.returncode is not None:
                    break
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", self._port)
                except OSError:
                    await asyncio.sleep(0.1)
                else:
                    writer.close()
                    await writer.wait_closed()
                    self._key = secrets.token_urlsafe(32)
                    return self
            raise BrowserDisplayError("The browser viewer could not start.")
        except BaseException as exc:
            await self.__aexit__(None, None, None)
            if isinstance(exc, (OSError, asyncio.TimeoutError)):
                raise BrowserDisplayError(
                    f"The browser display could not start ({type(exc).__name__})."
                ) from None
            raise

    async def __aexit__(self, *_args) -> None:
        self._key = ""
        self._port = 0
        for process in reversed(self._processes):
            if process.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=3)
                except asyncio.TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        process.kill()
                    await process.wait()
        self._processes.clear()

    def _view(self, key: str, request: Request) -> Response:
        if not self._key or not secrets.compare_digest(key, self._key):
            return HTMLResponse("This login window has closed.", status_code=410)
        host = request.url.hostname
        if host and ":" in host:
            host = f"[{host}]"
        settings = urlencode(
            {
                "host": host,
                # noVNC chooses WS/WSS from the public page, which may be HTTPS
                # even when a reverse proxy connects to this backend over HTTP.
                "port": request.url.port or "",
                "path": f"browser-login/socket/{key}",
                "autoconnect": "1",
                "resize": "scale",
                "view_only": "0",
                "logging": "warn",
            }
        )
        # Keep the session key in the fragment, out of static asset requests.
        return RedirectResponse(
            f"/browser-login/novnc/vnc.html#{settings}",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )

    async def _socket(self, websocket: WebSocket, key: str) -> None:
        # HTTP auth middleware does not cover WebSockets. Require the per-attempt
        # capability from the authenticated page and a same-origin connection.
        origin = urlsplit(websocket.headers.get("origin", ""))
        if (
            not self._key
            or not secrets.compare_digest(key, self._key)
            or origin.scheme not in ("http", "https")
            or origin.netloc != websocket.headers.get("host")
        ):
            await websocket.close(code=1008)
            return
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", self._port)
        except OSError:
            await websocket.close(code=1011)
            return
        await websocket.accept()

        async def to_browser() -> None:
            while data := await reader.read(65536):
                await websocket.send_bytes(data)

        async def to_display() -> None:
            while True:
                writer.write(await websocket.receive_bytes())
                await writer.drain()

        tasks = [asyncio.create_task(to_browser()), asyncio.create_task(to_display())]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await websocket.close()
